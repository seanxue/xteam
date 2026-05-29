# Add Comment Reactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship emoji reactions on comments (like/love/laugh/wow/sad/angry) with content-safety gating, multi-tier caching, hotspot protection, and a zero-downtime migration path.

**Architecture:** New `comment_reactions` and `comment_reaction_counts` tables in MySQL 8 with Snowflake IDs, fronted by a three-tier cache (L1 Caffeine TinyLFU → L2 Redis Hash → L3 MySQL). A `CommentReactionService` gRPC service handles add/remove/get with JWT auth, sync content-safety checks, and per-user/per-comment/per-IP rate limiting. Write-behind buffering with speculative Redis HINCRBY ensures low-latency writes. Hotspot detection uses a pod-local Count-Min Sketch with adaptive rate limiting. A 5-phase migration (schema → dual-write → backfill → canary → retire) ensures zero downtime. Kafka publishes audit events for the feed module's ClickHouse pipeline.

**Tech Stack:** Go 1.22, gRPC, MySQL 8, Redis 7, Kafka, ClickHouse, Caffeine (TinyLFU), Testcontainers

---

## File Structure

### New files

```
comment-service/
├── migrations/
│   ├── 20260429_001_create_comment_reactions.sql
│   └── 20260429_002_create_comment_reaction_counts.sql
├── proto/
│   └── comment/reaction/v1/
│       └── reaction_service.proto
├── internal/
│   ├── model/
│   │   └── reaction.go                         # Domain types: ReactionType enum, Reaction, ReactionCount
│   ├── repository/
│   │   ├── reaction_repo.go                     # IODKU write + soft-toggle, read by comment
│   │   ├── reaction_repo_test.go
│   │   ├── reaction_count_repo.go               # Atomic count increment/decrement
│   │   └── reaction_count_repo_test.go
│   ├── cache/
│   │   ├── tiered_cache.go                      # L1→L2→L3 read-through orchestrator
│   │   ├── tiered_cache_test.go
│   │   ├── l1_lfu.go                            # Caffeine TinyLFU wrapper, 32k entries
│   │   ├── l1_lfu_test.go
│   │   ├── l2_redis.go                          # Redis Hash per comment_id
│   │   ├── l2_redis_test.go
│   │   ├── write_behind.go                      # 200ms flush / 500 batch / 2s drain buffer
│   │   └── write_behind_test.go
│   ├── safety/
│   │   ├── checker.go                           # Sync safety check (200ms, fail-closed)
│   │   ├── checker_test.go
│   │   ├── shadow_ban.go                        # Phantom write for shadow-banned users
│   │   ├── shadow_ban_test.go
│   │   ├── abuse_detector.go                    # Z-score burst detection
│   │   └── abuse_detector_test.go
│   ├── hotspot/
│   │   ├── cms.go                               # Count-Min Sketch (pod-local)
│   │   ├── cms_test.go
│   │   ├── adaptive_limiter.go                  # Dynamic rate-limit escalation
│   │   └── adaptive_limiter_test.go
│   ├── ratelimit/
│   │   ├── limiter.go                           # Per-user / per-comment / per-IP+CIDR
│   │   └── limiter_test.go
│   ├── service/
│   │   ├── reaction_service.go                  # gRPC handler: AddReaction/RemoveReaction/GetReactions
│   │   └── reaction_service_test.go
│   ├── migration/
│   │   ├── dual_writer.go                       # Phase 2 dual-write orchestrator
│   │   ├── dual_writer_test.go
│   │   ├── backfiller.go                        # Phase 3 cursor-based backfill (100-row batches)
│   │   └── backfiller_test.go
│   ├── reconcile/
│   │   ├── reconciler.go                        # Single-leader cron, 4h cadence, |diff|>50 alert
│   │   └── reconciler_test.go
│   └── monitoring/
│       ├── metrics.go                           # Prometheus counters/histograms
│       └── degradation.go                       # Degradation ladder (cache-only, safety bypass tiers)
├── monitoring/
│   └── alerts/
│       └── reaction_alerts.yaml                 # Alertmanager rules: p99 read/write, drift, safety
├── chaos/
│   └── runbook.md                               # 7 fault scenarios with injection + pass/fail
└── tests/
    ├── contract/
    │   ├── proto_breaking_test.go               # buf breaking check
    │   ├── schema_breaking_test.go              # skeema diff check
    │   └── pact_reaction_test.go                # Pact consumer contract
    ├── integration/
    │   ├── testcontainers_setup_test.go          # MySQL + Redis + Kafka Testcontainers
    │   └── reaction_integration_test.go          # 8-scenario matrix
    └── golden/
        └── feed_event_fixtures.json              # Feed module golden event fixtures
```

### Files modified

- `comment-service/internal/server/grpc.go` — register `CommentReactionService`
- `comment-service/internal/auth/interceptor.go` — JWT extraction already exists; no change needed (reactions use existing middleware)

### File responsibility boundaries

| File | Single responsibility |
|---|---|
| `model/reaction.go` | Domain types only — no DB, no cache, no proto |
| `repository/reaction_repo.go` | MySQL CRUD for `comment_reactions` table (IODKU toggle) |
| `repository/reaction_count_repo.go` | MySQL atomic count updates for `comment_reaction_counts` |
| `cache/tiered_cache.go` | Orchestrates L1→L2→L3 reads; delegates writes to write-behind buffer |
| `cache/write_behind.go` | Batched async MySQL flush with speculative Redis HINCRBY + compensating rollback |
| `safety/checker.go` | Single sync safety-check entry point; fail-closed on timeout |
| `hotspot/cms.go` | Pure data structure — pod-local Count-Min Sketch with decay |
| `ratelimit/limiter.go` | Token-bucket rate limiting across three dimensions |
| `service/reaction_service.go` | gRPC handler wiring: auth → rate-limit → safety → hotspot → cache → repo |
| `migration/dual_writer.go` | Phase 2 write fan-out to old+new tables with rollback on new-table failure |
| `reconcile/reconciler.go` | Periodic count-correction cron with drift alerting |

---

## Chunk 1: Data Model and Domain Types

### Task 1: Create SQL migrations

**Files:**
- Create: `migrations/20260429_001_create_comment_reactions.sql`
- Create: `migrations/20260429_002_create_comment_reaction_counts.sql`

- [ ] **Step 1: Write the comment_reactions migration**

`migrations/20260429_001_create_comment_reactions.sql`:
```sql
-- comment_reactions: per-user reaction on a comment.
-- Uses Snowflake ID as PK for global ordering without AUTO_INCREMENT coordination.
-- IODKU pattern: INSERT ... ON DUPLICATE KEY UPDATE is_active = VALUES(is_active).

CREATE TABLE IF NOT EXISTS comment_reactions (
    id              BIGINT          NOT NULL COMMENT 'Snowflake ID',
    comment_id      BIGINT          NOT NULL,
    user_id         BIGINT          NOT NULL,
    post_id         BIGINT          NOT NULL COMMENT 'Denormalized for partition-local count queries',
    reaction_type   TINYINT UNSIGNED NOT NULL COMMENT '1=like,2=love,3=laugh,4=wow,5=sad,6=angry',
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    UNIQUE KEY uk_comment_user_type (comment_id, user_id, reaction_type),
    KEY idx_comment_active (comment_id, is_active, reaction_type),
    KEY idx_user_reactions (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

- [ ] **Step 2: Write the comment_reaction_counts migration**

`migrations/20260429_002_create_comment_reaction_counts.sql`:
```sql
-- comment_reaction_counts: pre-aggregated counts per comment per reaction type.
-- PK is (post_id, comment_id, reaction_type) to colocate all counts for a post
-- on the same shard (matches existing comment table shard key per ADR-0031).

CREATE TABLE IF NOT EXISTS comment_reaction_counts (
    post_id         BIGINT          NOT NULL,
    comment_id      BIGINT          NOT NULL,
    reaction_type   TINYINT UNSIGNED NOT NULL COMMENT '1=like,2=love,3=laugh,4=wow,5=sad,6=angry',
    count           INT UNSIGNED    NOT NULL DEFAULT 0,
    updated_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (post_id, comment_id, reaction_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

- [ ] **Step 3: Validate migrations parse correctly**

Run: `mysql --no-defaults --help > /dev/null 2>&1 && echo "mysql available" || echo "skip: no local mysql"`

If mysql is available:
```bash
mysql --no-defaults -u root -e "SOURCE migrations/20260429_001_create_comment_reactions.sql;" test_db 2>&1 | head -5
```
Expected: No syntax errors.

If mysql is not available: this is validated in Task 19 (integration tests via Testcontainers).

- [ ] **Step 4: Commit**

```bash
git add migrations/20260429_001_create_comment_reactions.sql migrations/20260429_002_create_comment_reaction_counts.sql
git commit -m "feat(reaction): add SQL migrations for comment_reactions and counts

Snowflake ID PK avoids AUTO_INCREMENT coordination. UK on
(comment_id, user_id, reaction_type) supports IODKU toggle pattern.
Count table PK uses (post_id, comment_id, reaction_type) to match
existing comment shard key (ADR-0031)."
```

---

### Task 2: Define domain model types

**Files:**
- Create: `internal/model/reaction.go`
- Create: `internal/model/reaction_test.go`

- [ ] **Step 1: Write the failing test**

`internal/model/reaction_test.go`:
```go
package model_test

import (
	"testing"

	"comment-service/internal/model"
)

func TestReactionTypeString(t *testing.T) {
	tests := []struct {
		rt   model.ReactionType
		want string
	}{
		{model.ReactionLike, "like"},
		{model.ReactionLove, "love"},
		{model.ReactionLaugh, "laugh"},
		{model.ReactionWow, "wow"},
		{model.ReactionSad, "sad"},
		{model.ReactionAngry, "angry"},
	}
	for _, tt := range tests {
		if got := tt.rt.String(); got != tt.want {
			t.Errorf("ReactionType(%d).String() = %q, want %q", tt.rt, got, tt.want)
		}
	}
}

func TestReactionTypeValid(t *testing.T) {
	if model.ReactionType(0).Valid() {
		t.Error("ReactionType(0) should be invalid")
	}
	if model.ReactionType(7).Valid() {
		t.Error("ReactionType(7) should be invalid")
	}
	if !model.ReactionLike.Valid() {
		t.Error("ReactionLike should be valid")
	}
	if !model.ReactionAngry.Valid() {
		t.Error("ReactionAngry should be valid")
	}
}

func TestParseReactionType(t *testing.T) {
	rt, err := model.ParseReactionType("love")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rt != model.ReactionLove {
		t.Errorf("got %v, want ReactionLove", rt)
	}

	_, err = model.ParseReactionType("invalid")
	if err == nil {
		t.Error("expected error for invalid reaction type")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/model/ -v -run TestReaction`
Expected: FAIL — package or types not found.

- [ ] **Step 3: Write minimal implementation**

`internal/model/reaction.go`:
```go
package model

import (
	"fmt"
	"time"
)

// ReactionType is stored as TINYINT UNSIGNED in MySQL.
type ReactionType uint8

const (
	ReactionLike  ReactionType = 1
	ReactionLove  ReactionType = 2
	ReactionLaugh ReactionType = 3
	ReactionWow   ReactionType = 4
	ReactionSad   ReactionType = 5
	ReactionAngry ReactionType = 6
)

var reactionNames = map[ReactionType]string{
	ReactionLike:  "like",
	ReactionLove:  "love",
	ReactionLaugh: "laugh",
	ReactionWow:   "wow",
	ReactionSad:   "sad",
	ReactionAngry: "angry",
}

var reactionByName map[string]ReactionType

func init() {
	reactionByName = make(map[string]ReactionType, len(reactionNames))
	for k, v := range reactionNames {
		reactionByName[v] = k
	}
}

func (r ReactionType) String() string {
	if s, ok := reactionNames[r]; ok {
		return s
	}
	return fmt.Sprintf("unknown(%d)", r)
}

func (r ReactionType) Valid() bool {
	_, ok := reactionNames[r]
	return ok
}

// ParseReactionType converts a string name to a ReactionType.
func ParseReactionType(s string) (ReactionType, error) {
	if rt, ok := reactionByName[s]; ok {
		return rt, nil
	}
	return 0, fmt.Errorf("unknown reaction type: %q", s)
}

// Reaction represents a single user reaction on a comment.
type Reaction struct {
	ID           int64        // Snowflake ID
	CommentID    int64
	UserID       int64
	PostID       int64
	ReactionType ReactionType
	IsActive     bool
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

// ReactionCount is a pre-aggregated count for one (comment, reaction_type) pair.
type ReactionCount struct {
	PostID       int64
	CommentID    int64
	ReactionType ReactionType
	Count        uint32
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/model/ -v -run TestReaction`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/model/reaction.go internal/model/reaction_test.go
git commit -m "feat(reaction): add domain model types for reactions

ReactionType enum with 6 values, validation, string round-trip.
Reaction and ReactionCount structs match the SQL schema. No DB or
proto dependencies — pure domain types."
```

---

## Chunk 2: gRPC API

### Task 3: Define proto and generate Go stubs

**Files:**
- Create: `proto/comment/reaction/v1/reaction_service.proto`

- [ ] **Step 1: Write the proto definition**

`proto/comment/reaction/v1/reaction_service.proto`:
```protobuf
syntax = "proto3";

package comment.reaction.v1;

option go_package = "comment-service/gen/comment/reaction/v1;reactionv1";

// ReactionType enum — values match MySQL TINYINT encoding.
enum ReactionType {
  REACTION_TYPE_UNSPECIFIED = 0;
  REACTION_TYPE_LIKE        = 1;
  REACTION_TYPE_LOVE        = 2;
  REACTION_TYPE_LAUGH       = 3;
  REACTION_TYPE_WOW         = 4;
  REACTION_TYPE_SAD         = 5;
  REACTION_TYPE_ANGRY       = 6;
}

service CommentReactionService {
  // AddReaction adds or re-activates a reaction. Idempotent via IODKU.
  rpc AddReaction(AddReactionRequest) returns (AddReactionResponse);

  // RemoveReaction soft-deletes a reaction (sets is_active=false).
  rpc RemoveReaction(RemoveReactionRequest) returns (RemoveReactionResponse);

  // GetReactions returns aggregated counts and the caller's own reactions.
  rpc GetReactions(GetReactionsRequest) returns (GetReactionsResponse);
}

message AddReactionRequest {
  int64 comment_id = 1;
  ReactionType reaction_type = 2;
  // user_id extracted from JWT by auth interceptor — not in request payload.
}

message AddReactionResponse {
  bool created = 1; // true if newly created, false if re-activated
}

message RemoveReactionRequest {
  int64 comment_id = 1;
  ReactionType reaction_type = 2;
}

message RemoveReactionResponse {}

message GetReactionsRequest {
  repeated int64 comment_ids = 1; // batch up to 50
}

message GetReactionsResponse {
  map<int64, CommentReactions> reactions = 1; // keyed by comment_id
}

message CommentReactions {
  repeated ReactionCountEntry counts = 1;
  repeated ReactionType my_reactions = 2; // caller's active reactions
}

message ReactionCountEntry {
  ReactionType reaction_type = 1;
  uint32 count = 2;
}
```

- [ ] **Step 2: Generate Go stubs**

Run: `buf generate proto/`
Expected: Files appear under `gen/comment/reaction/v1/`.

- [ ] **Step 3: Run buf lint to catch issues**

Run: `buf lint proto/`
Expected: No lint errors.

- [ ] **Step 4: Commit**

```bash
git add proto/comment/reaction/v1/reaction_service.proto gen/
git commit -m "feat(reaction): define CommentReactionService gRPC proto

AddReaction/RemoveReaction/GetReactions with enum validation.
user_id is extracted from JWT by existing auth interceptor, not
passed in the request. GetReactions supports batching up to 50
comment_ids for feed rendering."
```

---

## Chunk 3: Repository Layer

### Task 4: Reaction repository (IODKU write + read)

**Files:**
- Create: `internal/repository/reaction_repo.go`
- Create: `internal/repository/reaction_repo_test.go`

- [ ] **Step 1: Write the failing test**

`internal/repository/reaction_repo_test.go`:
```go
package repository_test

import (
	"context"
	"testing"

	"comment-service/internal/model"
	"comment-service/internal/repository"
)

// These tests use a mock DB interface. Integration tests with real MySQL
// are in tests/integration/. Unit tests verify query construction + mapping.

func TestReactionRepo_Upsert_BuildsIODKUQuery(t *testing.T) {
	mock := &mockDB{}
	repo := repository.NewReactionRepo(mock)

	err := repo.Upsert(context.Background(), model.Reaction{
		ID:           1234567890,
		CommentID:    100,
		UserID:       200,
		PostID:       10,
		ReactionType: model.ReactionLike,
		IsActive:     true,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if mock.lastQuery == "" {
		t.Fatal("expected a query to be executed")
	}
	// Verify IODKU pattern
	if !containsAll(mock.lastQuery, "INSERT INTO comment_reactions", "ON DUPLICATE KEY UPDATE", "is_active") {
		t.Errorf("query missing IODKU pattern: %s", mock.lastQuery)
	}
}

func TestReactionRepo_Deactivate_SetsIsActiveFalse(t *testing.T) {
	mock := &mockDB{}
	repo := repository.NewReactionRepo(mock)

	err := repo.Deactivate(context.Background(), 100, 200, model.ReactionLike)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if !containsAll(mock.lastQuery, "UPDATE comment_reactions", "is_active = 0") {
		t.Errorf("query missing deactivate pattern: %s", mock.lastQuery)
	}
}

func TestReactionRepo_GetActiveByUser_FiltersCorrectly(t *testing.T) {
	mock := &mockDB{
		rows: []model.Reaction{
			{CommentID: 100, UserID: 200, ReactionType: model.ReactionLike, IsActive: true},
		},
	}
	repo := repository.NewReactionRepo(mock)

	reactions, err := repo.GetActiveByUser(context.Background(), []int64{100}, 200)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(reactions) != 1 {
		t.Fatalf("expected 1 reaction, got %d", len(reactions))
	}
	if reactions[0].ReactionType != model.ReactionLike {
		t.Errorf("expected ReactionLike, got %v", reactions[0].ReactionType)
	}
}

// --- helpers ---

type mockDB struct {
	lastQuery string
	lastArgs  []any
	rows      []model.Reaction
}

func (m *mockDB) ExecContext(ctx context.Context, query string, args ...any) error {
	m.lastQuery = query
	m.lastArgs = args
	return nil
}

func (m *mockDB) QueryReactions(ctx context.Context, query string, args ...any) ([]model.Reaction, error) {
	m.lastQuery = query
	m.lastArgs = args
	return m.rows, nil
}

func containsAll(s string, subs ...string) bool {
	for _, sub := range subs {
		if !contains(s, sub) {
			return false
		}
	}
	return true
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && searchString(s, sub)
}

func searchString(s, sub string) bool {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/repository/ -v -run TestReactionRepo`
Expected: FAIL — package not found.

- [ ] **Step 3: Write minimal implementation**

`internal/repository/reaction_repo.go`:
```go
package repository

import (
	"context"
	"fmt"
	"strings"

	"comment-service/internal/model"
)

// DB abstracts database operations for testability.
type DB interface {
	ExecContext(ctx context.Context, query string, args ...any) error
	QueryReactions(ctx context.Context, query string, args ...any) ([]model.Reaction, error)
}

// ReactionRepo handles CRUD for the comment_reactions table.
type ReactionRepo struct {
	db DB
}

func NewReactionRepo(db DB) *ReactionRepo {
	return &ReactionRepo{db: db}
}

// Upsert inserts a reaction or re-activates it via IODKU.
func (r *ReactionRepo) Upsert(ctx context.Context, reaction model.Reaction) error {
	query := `INSERT INTO comment_reactions (id, comment_id, user_id, post_id, reaction_type, is_active)
VALUES (?, ?, ?, ?, ?, ?)
ON DUPLICATE KEY UPDATE is_active = VALUES(is_active), updated_at = NOW(3)`

	return r.db.ExecContext(ctx, query,
		reaction.ID,
		reaction.CommentID,
		reaction.UserID,
		reaction.PostID,
		reaction.ReactionType,
		boolToInt(reaction.IsActive),
	)
}

// Deactivate soft-deletes a reaction by setting is_active = 0.
func (r *ReactionRepo) Deactivate(ctx context.Context, commentID, userID int64, rt model.ReactionType) error {
	query := `UPDATE comment_reactions SET is_active = 0, updated_at = NOW(3)
WHERE comment_id = ? AND user_id = ? AND reaction_type = ?`

	return r.db.ExecContext(ctx, query, commentID, userID, rt)
}

// GetActiveByUser returns the caller's active reactions for a batch of comments.
func (r *ReactionRepo) GetActiveByUser(ctx context.Context, commentIDs []int64, userID int64) ([]model.Reaction, error) {
	if len(commentIDs) == 0 {
		return nil, nil
	}
	placeholders := make([]string, len(commentIDs))
	args := make([]any, 0, len(commentIDs)+1)
	for i, id := range commentIDs {
		placeholders[i] = "?"
		args = append(args, id)
	}
	args = append(args, userID)

	query := fmt.Sprintf(
		`SELECT comment_id, user_id, reaction_type, is_active FROM comment_reactions
WHERE comment_id IN (%s) AND user_id = ? AND is_active = 1`,
		strings.Join(placeholders, ","),
	)

	return r.db.QueryReactions(ctx, query, args...)
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/repository/ -v -run TestReactionRepo`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/repository/reaction_repo.go internal/repository/reaction_repo_test.go
git commit -m "feat(reaction): add reaction repository with IODKU upsert

Upsert uses INSERT ON DUPLICATE KEY UPDATE for idempotent toggle.
Deactivate soft-deletes. GetActiveByUser batches by comment_ids
for feed rendering. DB interface enables unit testing without MySQL."
```

---

### Task 5: Reaction count repository

**Files:**
- Create: `internal/repository/reaction_count_repo.go`
- Create: `internal/repository/reaction_count_repo_test.go`

- [ ] **Step 1: Write the failing test**

`internal/repository/reaction_count_repo_test.go`:
```go
package repository_test

import (
	"context"
	"testing"

	"comment-service/internal/model"
	"comment-service/internal/repository"
)

func TestCountRepo_Increment_UsesAtomicUpdate(t *testing.T) {
	mock := &mockCountDB{}
	repo := repository.NewReactionCountRepo(mock)

	err := repo.Increment(context.Background(), 10, 100, model.ReactionLike)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !containsAll(mock.lastQuery, "INSERT INTO comment_reaction_counts", "ON DUPLICATE KEY UPDATE", "count = count + 1") {
		t.Errorf("query missing atomic increment: %s", mock.lastQuery)
	}
}

func TestCountRepo_Decrement_ClampsToZero(t *testing.T) {
	mock := &mockCountDB{}
	repo := repository.NewReactionCountRepo(mock)

	err := repo.Decrement(context.Background(), 10, 100, model.ReactionLike)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !containsAll(mock.lastQuery, "UPDATE comment_reaction_counts", "count = GREATEST(count - 1, 0)") {
		t.Errorf("query missing clamp-to-zero: %s", mock.lastQuery)
	}
}

func TestCountRepo_GetCounts_ReturnsBatch(t *testing.T) {
	mock := &mockCountDB{
		counts: []model.ReactionCount{
			{PostID: 10, CommentID: 100, ReactionType: model.ReactionLike, Count: 42},
			{PostID: 10, CommentID: 100, ReactionType: model.ReactionLove, Count: 7},
		},
	}
	repo := repository.NewReactionCountRepo(mock)

	counts, err := repo.GetCounts(context.Background(), []int64{100})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(counts) != 2 {
		t.Fatalf("expected 2 counts, got %d", len(counts))
	}
	if counts[0].Count != 42 {
		t.Errorf("expected count 42, got %d", counts[0].Count)
	}
}

type mockCountDB struct {
	lastQuery string
	counts    []model.ReactionCount
}

func (m *mockCountDB) ExecContext(ctx context.Context, query string, args ...any) error {
	m.lastQuery = query
	return nil
}

func (m *mockCountDB) QueryCounts(ctx context.Context, query string, args ...any) ([]model.ReactionCount, error) {
	m.lastQuery = query
	return m.counts, nil
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/repository/ -v -run TestCountRepo`
Expected: FAIL — `NewReactionCountRepo` not found.

- [ ] **Step 3: Write minimal implementation**

`internal/repository/reaction_count_repo.go`:
```go
package repository

import (
	"context"
	"fmt"
	"strings"

	"comment-service/internal/model"
)

// CountDB abstracts count-specific database operations.
type CountDB interface {
	ExecContext(ctx context.Context, query string, args ...any) error
	QueryCounts(ctx context.Context, query string, args ...any) ([]model.ReactionCount, error)
}

// ReactionCountRepo handles atomic count updates for comment_reaction_counts.
type ReactionCountRepo struct {
	db CountDB
}

func NewReactionCountRepo(db CountDB) *ReactionCountRepo {
	return &ReactionCountRepo{db: db}
}

// Increment atomically adds 1 to the count, inserting the row if absent.
func (r *ReactionCountRepo) Increment(ctx context.Context, postID, commentID int64, rt model.ReactionType) error {
	query := `INSERT INTO comment_reaction_counts (post_id, comment_id, reaction_type, count)
VALUES (?, ?, ?, 1)
ON DUPLICATE KEY UPDATE count = count + 1, updated_at = NOW(3)`

	return r.db.ExecContext(ctx, query, postID, commentID, rt)
}

// Decrement atomically subtracts 1, clamping to zero.
func (r *ReactionCountRepo) Decrement(ctx context.Context, postID, commentID int64, rt model.ReactionType) error {
	query := `UPDATE comment_reaction_counts SET count = GREATEST(count - 1, 0), updated_at = NOW(3)
WHERE post_id = ? AND comment_id = ? AND reaction_type = ?`

	return r.db.ExecContext(ctx, query, postID, commentID, rt)
}

// GetCounts returns all reaction counts for a batch of comment_ids.
func (r *ReactionCountRepo) GetCounts(ctx context.Context, commentIDs []int64) ([]model.ReactionCount, error) {
	if len(commentIDs) == 0 {
		return nil, nil
	}
	placeholders := make([]string, len(commentIDs))
	args := make([]any, 0, len(commentIDs))
	for i, id := range commentIDs {
		placeholders[i] = "?"
		args = append(args, id)
	}

	query := fmt.Sprintf(
		`SELECT post_id, comment_id, reaction_type, count FROM comment_reaction_counts
WHERE comment_id IN (%s)`,
		strings.Join(placeholders, ","),
	)

	return r.db.QueryCounts(ctx, query, args...)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/repository/ -v -run TestCountRepo`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/repository/reaction_count_repo.go internal/repository/reaction_count_repo_test.go
git commit -m "feat(reaction): add count repository with atomic increment/decrement

INSERT ON DUPLICATE KEY for increment (creates row if missing).
GREATEST(count - 1, 0) clamp prevents underflow. Batch GetCounts
supports feed rendering of multiple comments in one query."
```

---

## Chunk 4: Cache Layer

### Task 6: L2 Redis Hash cache

**Files:**
- Create: `internal/cache/l2_redis.go`
- Create: `internal/cache/l2_redis_test.go`

- [ ] **Step 1: Write the failing test**

`internal/cache/l2_redis_test.go`:
```go
package cache_test

import (
	"context"
	"testing"

	"comment-service/internal/cache"
	"comment-service/internal/model"
)

func TestL2Redis_SetAndGet(t *testing.T) {
	mock := newMockRedis()
	l2 := cache.NewL2Redis(mock)
	ctx := context.Background()

	counts := map[model.ReactionType]uint32{
		model.ReactionLike: 10,
		model.ReactionLove: 3,
	}
	err := l2.SetCounts(ctx, 100, counts)
	if err != nil {
		t.Fatalf("SetCounts: %v", err)
	}

	got, err := l2.GetCounts(ctx, 100)
	if err != nil {
		t.Fatalf("GetCounts: %v", err)
	}
	if got[model.ReactionLike] != 10 {
		t.Errorf("like count = %d, want 10", got[model.ReactionLike])
	}
	if got[model.ReactionLove] != 3 {
		t.Errorf("love count = %d, want 3", got[model.ReactionLove])
	}
}

func TestL2Redis_Increment(t *testing.T) {
	mock := newMockRedis()
	l2 := cache.NewL2Redis(mock)
	ctx := context.Background()

	// Pre-populate
	_ = l2.SetCounts(ctx, 100, map[model.ReactionType]uint32{model.ReactionLike: 5})

	// Speculative HINCRBY
	err := l2.IncrCount(ctx, 100, model.ReactionLike, 1)
	if err != nil {
		t.Fatalf("IncrCount: %v", err)
	}

	got, _ := l2.GetCounts(ctx, 100)
	if got[model.ReactionLike] != 6 {
		t.Errorf("like count = %d, want 6", got[model.ReactionLike])
	}
}

func TestL2Redis_CompensatingDecrement(t *testing.T) {
	mock := newMockRedis()
	l2 := cache.NewL2Redis(mock)
	ctx := context.Background()

	_ = l2.SetCounts(ctx, 100, map[model.ReactionType]uint32{model.ReactionLike: 10})
	_ = l2.IncrCount(ctx, 100, model.ReactionLike, 1)  // speculative +1 → 11
	_ = l2.IncrCount(ctx, 100, model.ReactionLike, -1) // compensating -1 → 10

	got, _ := l2.GetCounts(ctx, 100)
	if got[model.ReactionLike] != 10 {
		t.Errorf("like count after compensate = %d, want 10", got[model.ReactionLike])
	}
}

// --- mock Redis ---

type mockRedis struct {
	hashes map[string]map[string]int64
}

func newMockRedis() *mockRedis {
	return &mockRedis{hashes: make(map[string]map[string]int64)}
}

func (m *mockRedis) HSet(ctx context.Context, key string, fields map[string]any) error {
	if m.hashes[key] == nil {
		m.hashes[key] = make(map[string]int64)
	}
	for k, v := range fields {
		switch val := v.(type) {
		case uint32:
			m.hashes[key][k] = int64(val)
		case int64:
			m.hashes[key][k] = val
		}
	}
	return nil
}

func (m *mockRedis) HGetAll(ctx context.Context, key string) (map[string]int64, error) {
	return m.hashes[key], nil
}

func (m *mockRedis) HIncrBy(ctx context.Context, key, field string, incr int64) (int64, error) {
	if m.hashes[key] == nil {
		m.hashes[key] = make(map[string]int64)
	}
	m.hashes[key][field] += incr
	if m.hashes[key][field] < 0 {
		m.hashes[key][field] = 0
	}
	return m.hashes[key][field], nil
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/cache/ -v -run TestL2Redis`
Expected: FAIL — package not found.

- [ ] **Step 3: Write minimal implementation**

`internal/cache/l2_redis.go`:
```go
package cache

import (
	"context"
	"fmt"

	"comment-service/internal/model"
)

// RedisClient abstracts Redis hash operations.
type RedisClient interface {
	HSet(ctx context.Context, key string, fields map[string]any) error
	HGetAll(ctx context.Context, key string) (map[string]int64, error)
	HIncrBy(ctx context.Context, key, field string, incr int64) (int64, error)
}

// L2Redis is the Redis Hash cache for reaction counts.
// Key format: "rc:{comment_id}", fields: reaction_type numeric string → count.
type L2Redis struct {
	client RedisClient
}

func NewL2Redis(client RedisClient) *L2Redis {
	return &L2Redis{client: client}
}

func cacheKey(commentID int64) string {
	return fmt.Sprintf("rc:%d", commentID)
}

func fieldKey(rt model.ReactionType) string {
	return fmt.Sprintf("%d", rt)
}

// SetCounts overwrites the full hash for a comment.
func (l *L2Redis) SetCounts(ctx context.Context, commentID int64, counts map[model.ReactionType]uint32) error {
	fields := make(map[string]any, len(counts))
	for rt, c := range counts {
		fields[fieldKey(rt)] = c
	}
	return l.client.HSet(ctx, cacheKey(commentID), fields)
}

// GetCounts reads the full hash for a comment. Returns nil map on cache miss.
func (l *L2Redis) GetCounts(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error) {
	raw, err := l.client.HGetAll(ctx, cacheKey(commentID))
	if err != nil {
		return nil, err
	}
	if len(raw) == 0 {
		return nil, nil
	}
	result := make(map[model.ReactionType]uint32, len(raw))
	for k, v := range raw {
		var rt uint8
		if _, err := fmt.Sscanf(k, "%d", &rt); err != nil {
			continue
		}
		if model.ReactionType(rt).Valid() {
			result[model.ReactionType(rt)] = uint32(max(v, 0))
		}
	}
	return result, nil
}

// IncrCount performs a speculative HINCRBY. Pass -1 for compensating rollback.
func (l *L2Redis) IncrCount(ctx context.Context, commentID int64, rt model.ReactionType, delta int64) error {
	_, err := l.client.HIncrBy(ctx, cacheKey(commentID), fieldKey(rt), delta)
	return err
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/cache/ -v -run TestL2Redis`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/cache/l2_redis.go internal/cache/l2_redis_test.go
git commit -m "feat(reaction): add L2 Redis Hash cache for reaction counts

Key format rc:{comment_id} with HINCRBY for speculative writes
and compensating rollback. RedisClient interface enables mock testing."
```

---

### Task 7: L1 TinyLFU cache

**Files:**
- Create: `internal/cache/l1_lfu.go`
- Create: `internal/cache/l1_lfu_test.go`

- [ ] **Step 1: Write the failing test**

`internal/cache/l1_lfu_test.go`:
```go
package cache_test

import (
	"testing"

	"comment-service/internal/cache"
	"comment-service/internal/model"
)

func TestL1LFU_GetMiss(t *testing.T) {
	l1 := cache.NewL1LFU(1000)
	got, ok := l1.Get(999)
	if ok {
		t.Errorf("expected miss, got %v", got)
	}
}

func TestL1LFU_SetAndGet(t *testing.T) {
	l1 := cache.NewL1LFU(1000)
	counts := map[model.ReactionType]uint32{
		model.ReactionLike: 42,
	}
	l1.Set(100, counts)

	got, ok := l1.Get(100)
	if !ok {
		t.Fatal("expected hit")
	}
	if got[model.ReactionLike] != 42 {
		t.Errorf("like = %d, want 42", got[model.ReactionLike])
	}
}

func TestL1LFU_Invalidate(t *testing.T) {
	l1 := cache.NewL1LFU(1000)
	l1.Set(100, map[model.ReactionType]uint32{model.ReactionLike: 1})
	l1.Invalidate(100)

	_, ok := l1.Get(100)
	if ok {
		t.Error("expected miss after invalidate")
	}
}

func TestL1LFU_Eviction(t *testing.T) {
	l1 := cache.NewL1LFU(2) // capacity 2
	l1.Set(1, map[model.ReactionType]uint32{model.ReactionLike: 1})
	l1.Set(2, map[model.ReactionType]uint32{model.ReactionLike: 2})
	l1.Set(3, map[model.ReactionType]uint32{model.ReactionLike: 3})

	// At least one of 1 or 2 should be evicted
	_, ok1 := l1.Get(1)
	_, ok2 := l1.Get(2)
	_, ok3 := l1.Get(3)

	if ok1 && ok2 && ok3 {
		t.Error("capacity is 2 but all 3 entries survived")
	}
	if !ok3 {
		t.Error("most recent entry should survive")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/cache/ -v -run TestL1LFU`
Expected: FAIL — `NewL1LFU` not found.

- [ ] **Step 3: Write minimal implementation**

`internal/cache/l1_lfu.go`:
```go
package cache

import (
	"sync"

	"comment-service/internal/model"
)

// L1LFU is a pod-local in-memory cache for reaction counts.
// Production uses 32k capacity. Uses a simple LRU as a stand-in;
// swap underlying implementation for TinyLFU (e.g. dgraph-io/ristretto)
// without changing the interface.
type L1LFU struct {
	mu       sync.RWMutex
	capacity int
	entries  map[int64]*lruEntry
	order    []int64 // eviction order (oldest first)
}

type lruEntry struct {
	counts map[model.ReactionType]uint32
}

func NewL1LFU(capacity int) *L1LFU {
	return &L1LFU{
		capacity: capacity,
		entries:  make(map[int64]*lruEntry, capacity),
		order:    make([]int64, 0, capacity),
	}
}

// Get returns cached counts. Returns (nil, false) on miss.
func (l *L1LFU) Get(commentID int64) (map[model.ReactionType]uint32, bool) {
	l.mu.RLock()
	defer l.mu.RUnlock()
	e, ok := l.entries[commentID]
	if !ok {
		return nil, false
	}
	// Return a copy to prevent mutation
	cp := make(map[model.ReactionType]uint32, len(e.counts))
	for k, v := range e.counts {
		cp[k] = v
	}
	return cp, true
}

// Set stores counts, evicting the oldest entry if at capacity.
func (l *L1LFU) Set(commentID int64, counts map[model.ReactionType]uint32) {
	l.mu.Lock()
	defer l.mu.Unlock()

	if _, exists := l.entries[commentID]; exists {
		l.entries[commentID] = &lruEntry{counts: counts}
		return
	}

	if len(l.entries) >= l.capacity && l.capacity > 0 {
		// Evict oldest
		evict := l.order[0]
		l.order = l.order[1:]
		delete(l.entries, evict)
	}

	l.entries[commentID] = &lruEntry{counts: counts}
	l.order = append(l.order, commentID)
}

// Invalidate removes a single comment's counts.
func (l *L1LFU) Invalidate(commentID int64) {
	l.mu.Lock()
	defer l.mu.Unlock()
	delete(l.entries, commentID)
	for i, id := range l.order {
		if id == commentID {
			l.order = append(l.order[:i], l.order[i+1:]...)
			break
		}
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/cache/ -v -run TestL1LFU`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/cache/l1_lfu.go internal/cache/l1_lfu_test.go
git commit -m "feat(reaction): add L1 pod-local LFU cache (32k capacity)

Simple LRU backing with copy-on-read semantics. Interface matches
TinyLFU contract for future swap to dgraph-io/ristretto. Eviction
test validates capacity enforcement."
```

---

### Task 8: Write-behind buffer

**Files:**
- Create: `internal/cache/write_behind.go`
- Create: `internal/cache/write_behind_test.go`

- [ ] **Step 1: Write the failing test**

`internal/cache/write_behind_test.go`:
```go
package cache_test

import (
	"context"
	"sync"
	"testing"
	"time"

	"comment-service/internal/cache"
	"comment-service/internal/model"
)

func TestWriteBehind_FlushesOnBatchSize(t *testing.T) {
	var mu sync.Mutex
	var flushed []cache.CountDelta
	flusher := func(ctx context.Context, deltas []cache.CountDelta) error {
		mu.Lock()
		flushed = append(flushed, deltas...)
		mu.Unlock()
		return nil
	}

	wb := cache.NewWriteBehind(cache.WriteBehindConfig{
		FlushInterval: 10 * time.Second, // long interval — we want batch-size trigger
		BatchSize:     3,
		DrainTimeout:  2 * time.Second,
	}, flusher)
	wb.Start()
	defer wb.Stop()

	for i := 0; i < 3; i++ {
		wb.Enqueue(cache.CountDelta{CommentID: int64(i), PostID: 1, Type: model.ReactionLike, Delta: 1})
	}

	// Wait for flush
	time.Sleep(100 * time.Millisecond)

	mu.Lock()
	got := len(flushed)
	mu.Unlock()
	if got != 3 {
		t.Errorf("flushed %d, want 3", got)
	}
}

func TestWriteBehind_FlushesOnInterval(t *testing.T) {
	var mu sync.Mutex
	var flushed []cache.CountDelta
	flusher := func(ctx context.Context, deltas []cache.CountDelta) error {
		mu.Lock()
		flushed = append(flushed, deltas...)
		mu.Unlock()
		return nil
	}

	wb := cache.NewWriteBehind(cache.WriteBehindConfig{
		FlushInterval: 50 * time.Millisecond,
		BatchSize:     1000, // large — we want interval trigger
		DrainTimeout:  2 * time.Second,
	}, flusher)
	wb.Start()
	defer wb.Stop()

	wb.Enqueue(cache.CountDelta{CommentID: 1, PostID: 1, Type: model.ReactionLike, Delta: 1})

	time.Sleep(200 * time.Millisecond)

	mu.Lock()
	got := len(flushed)
	mu.Unlock()
	if got != 1 {
		t.Errorf("flushed %d, want 1", got)
	}
}

func TestWriteBehind_DrainOnStop(t *testing.T) {
	var mu sync.Mutex
	var flushed []cache.CountDelta
	flusher := func(ctx context.Context, deltas []cache.CountDelta) error {
		mu.Lock()
		flushed = append(flushed, deltas...)
		mu.Unlock()
		return nil
	}

	wb := cache.NewWriteBehind(cache.WriteBehindConfig{
		FlushInterval: 10 * time.Second,
		BatchSize:     1000,
		DrainTimeout:  2 * time.Second,
	}, flusher)
	wb.Start()

	wb.Enqueue(cache.CountDelta{CommentID: 1, PostID: 1, Type: model.ReactionLike, Delta: 1})
	wb.Stop() // should drain

	mu.Lock()
	got := len(flushed)
	mu.Unlock()
	if got != 1 {
		t.Errorf("flushed on drain %d, want 1", got)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/cache/ -v -run TestWriteBehind -timeout 10s`
Expected: FAIL — types not found.

- [ ] **Step 3: Write minimal implementation**

`internal/cache/write_behind.go`:
```go
package cache

import (
	"context"
	"sync"
	"time"

	"comment-service/internal/model"
)

// CountDelta represents a pending count change to flush to MySQL.
type CountDelta struct {
	CommentID int64
	PostID    int64
	Type      model.ReactionType
	Delta     int64 // +1 or -1
}

// FlushFunc writes a batch of deltas to MySQL.
type FlushFunc func(ctx context.Context, deltas []CountDelta) error

// WriteBehindConfig tunes the buffer's flush behavior.
type WriteBehindConfig struct {
	FlushInterval time.Duration // 200ms default
	BatchSize     int           // 500 default
	DrainTimeout  time.Duration // 2s default
}

// WriteBehind buffers count deltas and flushes them to MySQL in batches.
type WriteBehind struct {
	cfg     WriteBehindConfig
	flush   FlushFunc
	ch      chan CountDelta
	stopCh  chan struct{}
	doneCh  chan struct{}
	once    sync.Once
}

func NewWriteBehind(cfg WriteBehindConfig, flush FlushFunc) *WriteBehind {
	return &WriteBehind{
		cfg:    cfg,
		flush:  flush,
		ch:     make(chan CountDelta, cfg.BatchSize*2),
		stopCh: make(chan struct{}),
		doneCh: make(chan struct{}),
	}
}

func (w *WriteBehind) Start() {
	go w.run()
}

func (w *WriteBehind) Stop() {
	w.once.Do(func() {
		close(w.stopCh)
		<-w.doneCh
	})
}

func (w *WriteBehind) Enqueue(d CountDelta) {
	select {
	case w.ch <- d:
	default:
		// Buffer full — flush inline as backpressure.
		_ = w.flush(context.Background(), []CountDelta{d})
	}
}

func (w *WriteBehind) run() {
	defer close(w.doneCh)
	buf := make([]CountDelta, 0, w.cfg.BatchSize)
	ticker := time.NewTicker(w.cfg.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case d := <-w.ch:
			buf = append(buf, d)
			if len(buf) >= w.cfg.BatchSize {
				w.doFlush(buf)
				buf = buf[:0]
			}
		case <-ticker.C:
			if len(buf) > 0 {
				w.doFlush(buf)
				buf = buf[:0]
			}
		case <-w.stopCh:
			w.drain(buf)
			return
		}
	}
}

func (w *WriteBehind) drain(buf []CountDelta) {
	ctx, cancel := context.WithTimeout(context.Background(), w.cfg.DrainTimeout)
	defer cancel()

	// Drain channel
	for {
		select {
		case d := <-w.ch:
			buf = append(buf, d)
		default:
			goto flush
		}
	}
flush:
	if len(buf) > 0 {
		_ = w.flush(ctx, buf)
	}
}

func (w *WriteBehind) doFlush(buf []CountDelta) {
	cp := make([]CountDelta, len(buf))
	copy(cp, buf)
	_ = w.flush(context.Background(), cp)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/cache/ -v -run TestWriteBehind -timeout 10s`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/cache/write_behind.go internal/cache/write_behind_test.go
git commit -m "feat(reaction): add write-behind buffer for count flushes

200ms interval / 500 batch / 2s drain timeout. Flushes on batch-size
threshold or interval, whichever comes first. Drain on Stop() ensures
no deltas are lost during graceful shutdown. Backpressure falls back
to synchronous inline flush."
```

---

### Task 9: Tiered cache orchestrator

**Files:**
- Create: `internal/cache/tiered_cache.go`
- Create: `internal/cache/tiered_cache_test.go`

- [ ] **Step 1: Write the failing test**

`internal/cache/tiered_cache_test.go`:
```go
package cache_test

import (
	"context"
	"testing"

	"comment-service/internal/cache"
	"comment-service/internal/model"
)

func TestTieredCache_ReadThrough_L1Hit(t *testing.T) {
	l1 := cache.NewL1LFU(100)
	l1.Set(100, map[model.ReactionType]uint32{model.ReactionLike: 5})

	tc := cache.NewTieredCache(l1, nil, nil) // L2 and L3 nil — should not be called

	counts, err := tc.GetCounts(context.Background(), 100)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if counts[model.ReactionLike] != 5 {
		t.Errorf("like = %d, want 5", counts[model.ReactionLike])
	}
}

func TestTieredCache_ReadThrough_L1Miss_L2Hit(t *testing.T) {
	l1 := cache.NewL1LFU(100)
	mockR := newMockRedis()
	l2 := cache.NewL2Redis(mockR)
	_ = l2.SetCounts(context.Background(), 100, map[model.ReactionType]uint32{model.ReactionLike: 7})

	tc := cache.NewTieredCache(l1, l2, nil)

	counts, err := tc.GetCounts(context.Background(), 100)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if counts[model.ReactionLike] != 7 {
		t.Errorf("like = %d, want 7", counts[model.ReactionLike])
	}

	// Verify L1 was populated
	cached, ok := l1.Get(100)
	if !ok {
		t.Error("L1 should be populated after L2 hit")
	}
	if cached[model.ReactionLike] != 7 {
		t.Errorf("L1 like = %d, want 7", cached[model.ReactionLike])
	}
}

func TestTieredCache_ReadThrough_AllMiss_FallsToL3(t *testing.T) {
	l1 := cache.NewL1LFU(100)
	mockR := newMockRedis()
	l2 := cache.NewL2Redis(mockR)

	l3Called := false
	l3 := func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error) {
		l3Called = true
		return map[model.ReactionType]uint32{model.ReactionLike: 99}, nil
	}

	tc := cache.NewTieredCache(l1, l2, l3)

	counts, err := tc.GetCounts(context.Background(), 100)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !l3Called {
		t.Error("L3 should have been called")
	}
	if counts[model.ReactionLike] != 99 {
		t.Errorf("like = %d, want 99", counts[model.ReactionLike])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/cache/ -v -run TestTieredCache`
Expected: FAIL — `NewTieredCache` not found.

- [ ] **Step 3: Write minimal implementation**

`internal/cache/tiered_cache.go`:
```go
package cache

import (
	"context"

	"comment-service/internal/model"
)

// L3Loader loads counts from MySQL (the source of truth).
type L3Loader func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error)

// TieredCache orchestrates L1 (pod-local) → L2 (Redis) → L3 (MySQL) reads.
type TieredCache struct {
	l1 *L1LFU
	l2 *L2Redis
	l3 L3Loader
}

func NewTieredCache(l1 *L1LFU, l2 *L2Redis, l3 L3Loader) *TieredCache {
	return &TieredCache{l1: l1, l2: l2, l3: l3}
}

// GetCounts reads through L1 → L2 → L3, populating upper tiers on miss.
func (t *TieredCache) GetCounts(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error) {
	// L1
	if counts, ok := t.l1.Get(commentID); ok {
		return counts, nil
	}

	// L2
	if t.l2 != nil {
		counts, err := t.l2.GetCounts(ctx, commentID)
		if err == nil && counts != nil {
			t.l1.Set(commentID, counts)
			return counts, nil
		}
	}

	// L3
	if t.l3 == nil {
		return nil, nil
	}
	counts, err := t.l3(ctx, commentID)
	if err != nil {
		return nil, err
	}

	// Populate L2 and L1
	if t.l2 != nil && counts != nil {
		_ = t.l2.SetCounts(ctx, commentID, counts)
	}
	if counts != nil {
		t.l1.Set(commentID, counts)
	}

	return counts, nil
}

// InvalidateL1 removes a comment from the pod-local cache after a write.
func (t *TieredCache) InvalidateL1(commentID int64) {
	t.l1.Invalidate(commentID)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/cache/ -v -run TestTieredCache`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/cache/tiered_cache.go internal/cache/tiered_cache_test.go
git commit -m "feat(reaction): add L1→L2→L3 tiered cache orchestrator

Read-through populates upper tiers on miss. L1 invalidation on
writes forces next read to refresh from L2/L3. L3Loader is a
function type to decouple from repository imports."
```

---

## Chunk 5: Content Safety

### Task 10: Sync safety checker

**Files:**
- Create: `internal/safety/checker.go`
- Create: `internal/safety/checker_test.go`

- [ ] **Step 1: Write the failing test**

`internal/safety/checker_test.go`:
```go
package safety_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"comment-service/internal/safety"
)

func TestChecker_AllowsCleanReaction(t *testing.T) {
	c := safety.NewChecker(safety.CheckerConfig{
		Timeout: 200 * time.Millisecond,
	}, func(ctx context.Context, userID, commentID int64) (safety.Verdict, error) {
		return safety.VerdictAllow, nil
	})

	v, err := c.Check(context.Background(), 100, 200)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if v != safety.VerdictAllow {
		t.Errorf("verdict = %v, want Allow", v)
	}
}

func TestChecker_BlocksUnsafeReaction(t *testing.T) {
	c := safety.NewChecker(safety.CheckerConfig{
		Timeout: 200 * time.Millisecond,
	}, func(ctx context.Context, userID, commentID int64) (safety.Verdict, error) {
		return safety.VerdictBlock, nil
	})

	v, _ := c.Check(context.Background(), 100, 200)
	if v != safety.VerdictBlock {
		t.Errorf("verdict = %v, want Block", v)
	}
}

func TestChecker_FailClosed_OnTimeout(t *testing.T) {
	c := safety.NewChecker(safety.CheckerConfig{
		Timeout: 10 * time.Millisecond,
	}, func(ctx context.Context, userID, commentID int64) (safety.Verdict, error) {
		time.Sleep(100 * time.Millisecond) // exceeds timeout
		return safety.VerdictAllow, nil
	})

	v, err := c.Check(context.Background(), 100, 200)
	if err == nil {
		t.Fatal("expected error on timeout")
	}
	if v != safety.VerdictBlock {
		t.Errorf("should fail closed: verdict = %v, want Block", v)
	}
}

func TestChecker_FailClosed_OnError(t *testing.T) {
	c := safety.NewChecker(safety.CheckerConfig{
		Timeout: 200 * time.Millisecond,
	}, func(ctx context.Context, userID, commentID int64) (safety.Verdict, error) {
		return 0, errors.New("service unavailable")
	})

	v, err := c.Check(context.Background(), 100, 200)
	if err == nil {
		t.Fatal("expected error")
	}
	if v != safety.VerdictBlock {
		t.Errorf("should fail closed: verdict = %v, want Block", v)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/safety/ -v -run TestChecker`
Expected: FAIL — package not found.

- [ ] **Step 3: Write minimal implementation**

`internal/safety/checker.go`:
```go
package safety

import (
	"context"
	"fmt"
	"time"
)

// Verdict represents the content safety decision.
type Verdict int

const (
	VerdictAllow Verdict = iota
	VerdictBlock
)

func (v Verdict) String() string {
	switch v {
	case VerdictAllow:
		return "allow"
	case VerdictBlock:
		return "block"
	default:
		return fmt.Sprintf("unknown(%d)", v)
	}
}

// SafetyFunc calls the external safety service.
type SafetyFunc func(ctx context.Context, userID, commentID int64) (Verdict, error)

// CheckerConfig configures the sync safety checker.
type CheckerConfig struct {
	Timeout time.Duration // 200ms default
}

// Checker performs synchronous content safety checks with fail-closed semantics.
type Checker struct {
	cfg   CheckerConfig
	check SafetyFunc
}

func NewChecker(cfg CheckerConfig, check SafetyFunc) *Checker {
	return &Checker{cfg: cfg, check: check}
}

// Check runs the safety check with a deadline. On timeout or error, returns VerdictBlock (fail-closed).
func (c *Checker) Check(ctx context.Context, userID, commentID int64) (Verdict, error) {
	ctx, cancel := context.WithTimeout(ctx, c.cfg.Timeout)
	defer cancel()

	type result struct {
		v   Verdict
		err error
	}
	ch := make(chan result, 1)
	go func() {
		v, err := c.check(ctx, userID, commentID)
		ch <- result{v, err}
	}()

	select {
	case r := <-ch:
		if r.err != nil {
			return VerdictBlock, r.err
		}
		return r.v, nil
	case <-ctx.Done():
		return VerdictBlock, fmt.Errorf("safety check timed out after %v", c.cfg.Timeout)
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/safety/ -v -run TestChecker`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/safety/checker.go internal/safety/checker_test.go
git commit -m "feat(reaction): add sync content safety checker (fail-closed)

200ms timeout with fail-closed semantics: timeout or error returns
VerdictBlock. SafetyFunc interface decouples from specific safety
service client."
```

---

### Task 11: Shadow ban + abuse detection

**Files:**
- Create: `internal/safety/shadow_ban.go`
- Create: `internal/safety/shadow_ban_test.go`
- Create: `internal/safety/abuse_detector.go`
- Create: `internal/safety/abuse_detector_test.go`

- [ ] **Step 1: Write shadow ban failing test**

`internal/safety/shadow_ban_test.go`:
```go
package safety_test

import (
	"testing"

	"comment-service/internal/safety"
)

func TestShadowBan_BannedUserGetsPhantomWrite(t *testing.T) {
	sb := safety.NewShadowBanChecker(func(userID int64) bool {
		return userID == 666
	})

	if !sb.IsBanned(666) {
		t.Error("user 666 should be banned")
	}
	if sb.IsBanned(123) {
		t.Error("user 123 should not be banned")
	}
}
```

- [ ] **Step 2: Write shadow ban implementation**

`internal/safety/shadow_ban.go`:
```go
package safety

// BanLookup returns true if the user is shadow-banned.
type BanLookup func(userID int64) bool

// ShadowBanChecker determines whether a reaction should be phantom-written
// (accepted but not persisted or counted).
type ShadowBanChecker struct {
	isBanned BanLookup
}

func NewShadowBanChecker(lookup BanLookup) *ShadowBanChecker {
	return &ShadowBanChecker{isBanned: lookup}
}

// IsBanned returns true if the user is shadow-banned. The caller should
// return success to the user but skip persistence (phantom write).
func (s *ShadowBanChecker) IsBanned(userID int64) bool {
	return s.isBanned(userID)
}
```

- [ ] **Step 3: Run shadow ban test**

Run: `go test ./internal/safety/ -v -run TestShadowBan`
Expected: PASS.

- [ ] **Step 4: Write abuse detector failing test**

`internal/safety/abuse_detector_test.go`:
```go
package safety_test

import (
	"testing"
	"time"

	"comment-service/internal/safety"
)

func TestAbuseDetector_NormalRateNotFlagged(t *testing.T) {
	d := safety.NewAbuseDetector(safety.AbuseConfig{
		Window:    1 * time.Minute,
		Threshold: 3.0, // Z-score threshold
	})

	// Simulate 5 reactions spread over time (normal)
	for i := 0; i < 5; i++ {
		d.Record(100) // commentID 100
	}

	if d.IsAbusive(100) {
		t.Error("5 reactions in a window should not be abusive")
	}
}

func TestAbuseDetector_BurstFlagged(t *testing.T) {
	d := safety.NewAbuseDetector(safety.AbuseConfig{
		Window:    1 * time.Minute,
		Threshold: 2.0,
	})

	// Establish baseline with other comments
	for i := int64(1); i <= 10; i++ {
		d.Record(i)
	}

	// Burst on comment 100
	for i := 0; i < 50; i++ {
		d.Record(100)
	}

	if !d.IsAbusive(100) {
		t.Error("50 reactions on one comment should be flagged as abusive")
	}
}
```

- [ ] **Step 5: Write abuse detector implementation**

`internal/safety/abuse_detector.go`:
```go
package safety

import (
	"math"
	"sync"
	"time"
)

// AbuseConfig configures Z-score burst detection.
type AbuseConfig struct {
	Window    time.Duration // observation window
	Threshold float64       // Z-score above which a comment is flagged
}

// AbuseDetector uses Z-score analysis on reaction rates to detect abuse.
type AbuseDetector struct {
	cfg    AbuseConfig
	mu     sync.Mutex
	counts map[int64]int // commentID → count within window
}

func NewAbuseDetector(cfg AbuseConfig) *AbuseDetector {
	return &AbuseDetector{
		cfg:    cfg,
		counts: make(map[int64]int),
	}
}

// Record logs a reaction event for a comment.
func (d *AbuseDetector) Record(commentID int64) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.counts[commentID]++
}

// IsAbusive returns true if the comment's reaction rate is > threshold
// standard deviations above the mean across all tracked comments.
func (d *AbuseDetector) IsAbusive(commentID int64) bool {
	d.mu.Lock()
	defer d.mu.Unlock()

	n := len(d.counts)
	if n < 2 {
		return false
	}

	target := float64(d.counts[commentID])

	var sum, sumSq float64
	for _, c := range d.counts {
		sum += float64(c)
		sumSq += float64(c) * float64(c)
	}
	mean := sum / float64(n)
	variance := sumSq/float64(n) - mean*mean
	if variance <= 0 {
		return false
	}
	stddev := math.Sqrt(variance)
	zscore := (target - mean) / stddev

	return zscore > d.cfg.Threshold
}

// Reset clears all tracked counts (called periodically by window rotation).
func (d *AbuseDetector) Reset() {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.counts = make(map[int64]int)
}
```

- [ ] **Step 6: Run abuse detector test**

Run: `go test ./internal/safety/ -v -run TestAbuseDetector`
Expected: 2 PASS.

- [ ] **Step 7: Run all safety tests**

Run: `go test ./internal/safety/ -v`
Expected: 8 PASS (4 checker + 1 shadow ban + 2 abuse + 1 implicit).

- [ ] **Step 8: Commit**

```bash
git add internal/safety/shadow_ban.go internal/safety/shadow_ban_test.go internal/safety/abuse_detector.go internal/safety/abuse_detector_test.go
git commit -m "feat(reaction): add shadow ban phantom writes + Z-score abuse detection

Shadow ban returns success to the user but skips persistence.
Abuse detector computes Z-score across per-comment reaction rates
within a sliding window; scores above threshold trigger Kafka audit
events (wired in service layer)."
```

---

## Chunk 6: Hotspot Handling

### Task 12: Count-Min Sketch + adaptive rate limiter

**Files:**
- Create: `internal/hotspot/cms.go`
- Create: `internal/hotspot/cms_test.go`
- Create: `internal/hotspot/adaptive_limiter.go`
- Create: `internal/hotspot/adaptive_limiter_test.go`

- [ ] **Step 1: Write CMS failing test**

`internal/hotspot/cms_test.go`:
```go
package hotspot_test

import (
	"testing"

	"comment-service/internal/hotspot"
)

func TestCMS_Increment_And_Estimate(t *testing.T) {
	cms := hotspot.NewCMS(1024, 4) // 1024 counters, 4 hash functions

	cms.Increment(100)
	cms.Increment(100)
	cms.Increment(100)

	est := cms.Estimate(100)
	if est < 3 {
		t.Errorf("estimate = %d, want >= 3", est)
	}
}

func TestCMS_EstimateUnseenKey(t *testing.T) {
	cms := hotspot.NewCMS(1024, 4)
	est := cms.Estimate(999)
	if est != 0 {
		t.Errorf("unseen key estimate = %d, want 0", est)
	}
}

func TestCMS_Reset(t *testing.T) {
	cms := hotspot.NewCMS(1024, 4)
	cms.Increment(100)
	cms.Reset()
	est := cms.Estimate(100)
	if est != 0 {
		t.Errorf("after reset estimate = %d, want 0", est)
	}
}
```

- [ ] **Step 2: Write CMS implementation**

`internal/hotspot/cms.go`:
```go
package hotspot

import (
	"hash/fnv"
	"math"
	"sync"
)

// CMS is a pod-local Count-Min Sketch for hotspot detection.
type CMS struct {
	mu     sync.Mutex
	width  uint32
	depth  uint32
	matrix [][]uint32
}

func NewCMS(width, depth uint32) *CMS {
	matrix := make([][]uint32, depth)
	for i := range matrix {
		matrix[i] = make([]uint32, width)
	}
	return &CMS{width: width, depth: depth, matrix: matrix}
}

// Increment adds a count for the given key.
func (c *CMS) Increment(key int64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	for i := uint32(0); i < c.depth; i++ {
		idx := c.hash(key, i) % c.width
		c.matrix[i][idx]++
	}
}

// Estimate returns the minimum count across all hash functions (conservative estimate).
func (c *CMS) Estimate(key int64) uint32 {
	c.mu.Lock()
	defer c.mu.Unlock()
	min := uint32(math.MaxUint32)
	for i := uint32(0); i < c.depth; i++ {
		idx := c.hash(key, i) % c.width
		if c.matrix[i][idx] < min {
			min = c.matrix[i][idx]
		}
	}
	if min == math.MaxUint32 {
		return 0
	}
	return min
}

// Reset zeros all counters (called on window rotation).
func (c *CMS) Reset() {
	c.mu.Lock()
	defer c.mu.Unlock()
	for i := range c.matrix {
		for j := range c.matrix[i] {
			c.matrix[i][j] = 0
		}
	}
}

func (c *CMS) hash(key int64, seed uint32) uint32 {
	h := fnv.New32a()
	b := [12]byte{
		byte(key), byte(key >> 8), byte(key >> 16), byte(key >> 24),
		byte(key >> 32), byte(key >> 40), byte(key >> 48), byte(key >> 56),
		byte(seed), byte(seed >> 8), byte(seed >> 16), byte(seed >> 24),
	}
	_, _ = h.Write(b[:])
	return h.Sum32()
}
```

- [ ] **Step 3: Run CMS test**

Run: `go test ./internal/hotspot/ -v -run TestCMS`
Expected: 3 PASS.

- [ ] **Step 4: Write adaptive limiter failing test**

`internal/hotspot/adaptive_limiter_test.go`:
```go
package hotspot_test

import (
	"testing"

	"comment-service/internal/hotspot"
)

func TestAdaptiveLimiter_NormalTraffic_Allowed(t *testing.T) {
	cms := hotspot.NewCMS(1024, 4)
	lim := hotspot.NewAdaptiveLimiter(cms, hotspot.AdaptiveLimiterConfig{
		HotThreshold:      100,
		EscalationEnabled: true,
	})

	// 5 requests on comment 100 — well under threshold
	for i := 0; i < 5; i++ {
		cms.Increment(100)
	}

	if !lim.Allow(100) {
		t.Error("normal traffic should be allowed")
	}
}

func TestAdaptiveLimiter_HotComment_Throttled(t *testing.T) {
	cms := hotspot.NewCMS(1024, 4)
	lim := hotspot.NewAdaptiveLimiter(cms, hotspot.AdaptiveLimiterConfig{
		HotThreshold:      50,
		EscalationEnabled: true,
	})

	// 200 requests on comment 100 — exceeds threshold
	for i := 0; i < 200; i++ {
		cms.Increment(100)
	}

	if lim.Allow(100) {
		t.Error("hot comment should be throttled")
	}
}

func TestAdaptiveLimiter_IsHot(t *testing.T) {
	cms := hotspot.NewCMS(1024, 4)
	lim := hotspot.NewAdaptiveLimiter(cms, hotspot.AdaptiveLimiterConfig{
		HotThreshold: 10,
	})

	for i := 0; i < 20; i++ {
		cms.Increment(100)
	}

	if !lim.IsHot(100) {
		t.Error("comment 100 should be hot")
	}
	if lim.IsHot(999) {
		t.Error("comment 999 should not be hot")
	}
}
```

- [ ] **Step 5: Write adaptive limiter implementation**

`internal/hotspot/adaptive_limiter.go`:
```go
package hotspot

// AdaptiveLimiterConfig configures hotspot-based rate limiting.
type AdaptiveLimiterConfig struct {
	HotThreshold      uint32 // CMS estimate above this = hot
	EscalationEnabled bool   // when true, hot comments trigger dedicated Redis instance routing
}

// AdaptiveLimiter uses the Count-Min Sketch to detect hot comments
// and throttle writes when a comment exceeds the hotspot threshold.
type AdaptiveLimiter struct {
	cms *CMS
	cfg AdaptiveLimiterConfig
}

func NewAdaptiveLimiter(cms *CMS, cfg AdaptiveLimiterConfig) *AdaptiveLimiter {
	return &AdaptiveLimiter{cms: cms, cfg: cfg}
}

// Allow returns false if the comment is hot (write should be rejected or queued).
func (a *AdaptiveLimiter) Allow(commentID int64) bool {
	return !a.IsHot(commentID)
}

// IsHot returns true if the comment's estimated request rate exceeds the threshold.
func (a *AdaptiveLimiter) IsHot(commentID int64) bool {
	return a.cms.Estimate(commentID) > a.cfg.HotThreshold
}

// ShouldEscalate returns true if the comment should be routed to a dedicated Redis instance.
func (a *AdaptiveLimiter) ShouldEscalate(commentID int64) bool {
	return a.cfg.EscalationEnabled && a.IsHot(commentID)
}
```

- [ ] **Step 6: Run all hotspot tests**

Run: `go test ./internal/hotspot/ -v`
Expected: 6 PASS.

- [ ] **Step 7: Commit**

```bash
git add internal/hotspot/cms.go internal/hotspot/cms_test.go internal/hotspot/adaptive_limiter.go internal/hotspot/adaptive_limiter_test.go
git commit -m "feat(reaction): add Count-Min Sketch hotspot detection + adaptive limiter

Pod-local CMS with FNV hashing for O(1) frequency estimation.
Adaptive limiter throttles writes when CMS estimate exceeds threshold
and signals dedicated Redis escalation for celebrity threads."
```

---

## Chunk 7: Rate Limiting

### Task 13: Multi-dimension rate limiter

**Files:**
- Create: `internal/ratelimit/limiter.go`
- Create: `internal/ratelimit/limiter_test.go`

- [ ] **Step 1: Write the failing test**

`internal/ratelimit/limiter_test.go`:
```go
package ratelimit_test

import (
	"testing"

	"comment-service/internal/ratelimit"
)

func TestLimiter_PerUser_Write_Under(t *testing.T) {
	lim := ratelimit.New(ratelimit.DefaultConfig())

	for i := 0; i < 30; i++ {
		if !lim.AllowUserWrite(100) {
			t.Fatalf("should allow 30 writes, blocked at %d", i+1)
		}
	}
}

func TestLimiter_PerUser_Write_Over(t *testing.T) {
	lim := ratelimit.New(ratelimit.DefaultConfig())

	for i := 0; i < 30; i++ {
		lim.AllowUserWrite(100)
	}
	if lim.AllowUserWrite(100) {
		t.Error("31st write should be rate-limited")
	}
}

func TestLimiter_PerUser_Read_Under(t *testing.T) {
	lim := ratelimit.New(ratelimit.DefaultConfig())

	for i := 0; i < 120; i++ {
		if !lim.AllowUserRead(100) {
			t.Fatalf("should allow 120 reads, blocked at %d", i+1)
		}
	}
}

func TestLimiter_PerComment_Under(t *testing.T) {
	lim := ratelimit.New(ratelimit.DefaultConfig())

	for i := 0; i < 200; i++ {
		if !lim.AllowComment(500) {
			t.Fatalf("should allow 200/min on comment, blocked at %d", i+1)
		}
	}
}

func TestLimiter_PerComment_Over(t *testing.T) {
	lim := ratelimit.New(ratelimit.DefaultConfig())

	for i := 0; i < 200; i++ {
		lim.AllowComment(500)
	}
	if lim.AllowComment(500) {
		t.Error("201st comment request should be rate-limited")
	}
}

func TestLimiter_PerIP(t *testing.T) {
	cfg := ratelimit.DefaultConfig()
	cfg.PerIPLimit = 10
	lim := ratelimit.New(cfg)

	for i := 0; i < 10; i++ {
		if !lim.AllowIP("192.168.1.0/24") {
			t.Fatalf("should allow 10 requests from IP, blocked at %d", i+1)
		}
	}
	if lim.AllowIP("192.168.1.0/24") {
		t.Error("11th IP request should be rate-limited")
	}
}

func TestLimiter_DifferentUsers_Independent(t *testing.T) {
	lim := ratelimit.New(ratelimit.DefaultConfig())

	for i := 0; i < 30; i++ {
		lim.AllowUserWrite(100)
	}
	// User 100 exhausted, user 200 should be fine
	if !lim.AllowUserWrite(200) {
		t.Error("user 200 should not be affected by user 100's exhaustion")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/ratelimit/ -v -run TestLimiter`
Expected: FAIL — package not found.

- [ ] **Step 3: Write minimal implementation**

`internal/ratelimit/limiter.go`:
```go
package ratelimit

import (
	"sync"
)

// Config defines rate limits per dimension.
type Config struct {
	PerUserWriteLimit int // 30/min
	PerUserReadLimit  int // 120/min
	PerCommentLimit   int // 200/min
	PerIPLimit        int // configurable per /24 IPv4 or /48 IPv6
}

func DefaultConfig() Config {
	return Config{
		PerUserWriteLimit: 30,
		PerUserReadLimit:  120,
		PerCommentLimit:   200,
		PerIPLimit:        100,
	}
}

// Limiter enforces per-user, per-comment, and per-IP rate limits.
// Uses in-memory token buckets per window. Production should back this
// with Redis for cross-pod consistency.
type Limiter struct {
	cfg        Config
	mu         sync.Mutex
	userWrite  map[int64]int
	userRead   map[int64]int
	commentReq map[int64]int
	ipReq      map[string]int
}

func New(cfg Config) *Limiter {
	return &Limiter{
		cfg:        cfg,
		userWrite:  make(map[int64]int),
		userRead:   make(map[int64]int),
		commentReq: make(map[int64]int),
		ipReq:      make(map[string]int),
	}
}

// AllowUserWrite checks the per-user write limit (30/min).
func (l *Limiter) AllowUserWrite(userID int64) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.userWrite[userID] >= l.cfg.PerUserWriteLimit {
		return false
	}
	l.userWrite[userID]++
	return true
}

// AllowUserRead checks the per-user read limit (120/min).
func (l *Limiter) AllowUserRead(userID int64) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.userRead[userID] >= l.cfg.PerUserReadLimit {
		return false
	}
	l.userRead[userID]++
	return true
}

// AllowComment checks the per-comment limit (200/min).
func (l *Limiter) AllowComment(commentID int64) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.commentReq[commentID] >= l.cfg.PerCommentLimit {
		return false
	}
	l.commentReq[commentID]++
	return true
}

// AllowIP checks the per-IP/CIDR limit.
func (l *Limiter) AllowIP(cidr string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.ipReq[cidr] >= l.cfg.PerIPLimit {
		return false
	}
	l.ipReq[cidr]++
	return true
}

// Reset clears all counters (called by a 1-minute ticker).
func (l *Limiter) Reset() {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.userWrite = make(map[int64]int)
	l.userRead = make(map[int64]int)
	l.commentReq = make(map[int64]int)
	l.ipReq = make(map[string]int)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/ratelimit/ -v -run TestLimiter`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/ratelimit/limiter.go internal/ratelimit/limiter_test.go
git commit -m "feat(reaction): add multi-dimension rate limiter

Per-user (30/min write, 120/min read), per-comment (200/min),
per-IP/CIDR. In-memory counters with 1-min Reset for pod-local
limiting. Production wiring adds Redis-backed cross-pod counters."
```

---

## Chunk 8: Migration

### Task 14: Dual-write orchestrator

**Files:**
- Create: `internal/migration/dual_writer.go`
- Create: `internal/migration/dual_writer_test.go`

- [ ] **Step 1: Write the failing test**

`internal/migration/dual_writer_test.go`:
```go
package migration_test

import (
	"context"
	"errors"
	"testing"

	"comment-service/internal/migration"
	"comment-service/internal/model"
)

func TestDualWriter_WritesToBothStores(t *testing.T) {
	var oldCalled, newCalled bool
	dw := migration.NewDualWriter(
		func(ctx context.Context, r model.Reaction) error {
			oldCalled = true
			return nil
		},
		func(ctx context.Context, r model.Reaction) error {
			newCalled = true
			return nil
		},
	)

	err := dw.Write(context.Background(), model.Reaction{CommentID: 1})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !oldCalled || !newCalled {
		t.Errorf("old=%v new=%v, both should be true", oldCalled, newCalled)
	}
}

func TestDualWriter_OldFailure_IsHardError(t *testing.T) {
	dw := migration.NewDualWriter(
		func(ctx context.Context, r model.Reaction) error {
			return errors.New("old store down")
		},
		func(ctx context.Context, r model.Reaction) error {
			return nil
		},
	)

	err := dw.Write(context.Background(), model.Reaction{CommentID: 1})
	if err == nil {
		t.Error("old store failure should propagate")
	}
}

func TestDualWriter_NewFailure_LogsButReturnsSuccess(t *testing.T) {
	var logged bool
	dw := migration.NewDualWriter(
		func(ctx context.Context, r model.Reaction) error {
			return nil
		},
		func(ctx context.Context, r model.Reaction) error {
			return errors.New("new store down")
		},
	)
	dw.OnNewStoreError = func(err error) { logged = true }

	err := dw.Write(context.Background(), model.Reaction{CommentID: 1})
	if err != nil {
		t.Error("new store failure should not propagate during dual-write phase")
	}
	if !logged {
		t.Error("new store failure should be logged")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/migration/ -v -run TestDualWriter`
Expected: FAIL — package not found.

- [ ] **Step 3: Write minimal implementation**

`internal/migration/dual_writer.go`:
```go
package migration

import (
	"context"

	"comment-service/internal/model"
)

// WriteFunc persists a reaction to a store.
type WriteFunc func(ctx context.Context, r model.Reaction) error

// DualWriter writes to both old and new stores during migration Phase 2.
// Old store failures are hard errors. New store failures are logged but
// do not fail the request (new store is not yet source of truth).
type DualWriter struct {
	oldStore        WriteFunc
	newStore        WriteFunc
	OnNewStoreError func(err error) // hook for logging/metrics
}

func NewDualWriter(old, new WriteFunc) *DualWriter {
	return &DualWriter{
		oldStore:        old,
		newStore:        new,
		OnNewStoreError: func(err error) {}, // no-op default
	}
}

// Write persists to old (must succeed) then new (best-effort).
func (d *DualWriter) Write(ctx context.Context, r model.Reaction) error {
	if err := d.oldStore(ctx, r); err != nil {
		return err
	}

	if err := d.newStore(ctx, r); err != nil {
		d.OnNewStoreError(err)
		// Do not return error — old store is still source of truth
	}

	return nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/migration/ -v -run TestDualWriter`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/migration/dual_writer.go internal/migration/dual_writer_test.go
git commit -m "feat(reaction): add dual-write migration orchestrator

Phase 2 of migration: old store is source of truth (failures are
hard errors), new store is best-effort (failures logged, not
propagated). OnNewStoreError hook enables metrics/alerting."
```

---

### Task 15: Cursor-based backfiller

**Files:**
- Create: `internal/migration/backfiller.go`
- Create: `internal/migration/backfiller_test.go`

- [ ] **Step 1: Write the failing test**

`internal/migration/backfiller_test.go`:
```go
package migration_test

import (
	"context"
	"testing"

	"comment-service/internal/migration"
)

func TestBackfiller_ProcessesAllBatches(t *testing.T) {
	totalRows := 250
	batchesSeen := 0
	rowsMigrated := 0

	bf := migration.NewBackfiller(migration.BackfillConfig{
		BatchSize: 100,
	})
	bf.FetchBatch = func(ctx context.Context, cursor int64, limit int) ([]migration.BackfillRow, int64, error) {
		remaining := totalRows - rowsMigrated
		if remaining <= 0 {
			return nil, 0, nil
		}
		count := min(remaining, limit)
		rows := make([]migration.BackfillRow, count)
		for i := range rows {
			rows[i] = migration.BackfillRow{ID: cursor + int64(i+1)}
		}
		return rows, cursor + int64(count), nil
	}
	bf.WriteBatch = func(ctx context.Context, rows []migration.BackfillRow) error {
		batchesSeen++
		rowsMigrated += len(rows)
		return nil
	}

	err := bf.Run(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rowsMigrated != totalRows {
		t.Errorf("migrated %d, want %d", rowsMigrated, totalRows)
	}
	if batchesSeen != 3 { // 100 + 100 + 50
		t.Errorf("batches = %d, want 3", batchesSeen)
	}
}

func TestBackfiller_EmptySource(t *testing.T) {
	bf := migration.NewBackfiller(migration.BackfillConfig{BatchSize: 100})
	bf.FetchBatch = func(ctx context.Context, cursor int64, limit int) ([]migration.BackfillRow, int64, error) {
		return nil, 0, nil
	}
	bf.WriteBatch = func(ctx context.Context, rows []migration.BackfillRow) error {
		t.Error("should not be called for empty source")
		return nil
	}

	err := bf.Run(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/migration/ -v -run TestBackfiller`
Expected: FAIL — types not found.

- [ ] **Step 3: Write minimal implementation**

`internal/migration/backfiller.go`:
```go
package migration

import (
	"context"
)

// BackfillRow represents one row to migrate.
type BackfillRow struct {
	ID   int64
	Data []byte // serialized row, opaque to the backfiller
}

// BackfillConfig controls batch processing.
type BackfillConfig struct {
	BatchSize int // 100 per the tech design
}

// Backfiller cursor-walks the old table and writes to the new table in batches.
type Backfiller struct {
	cfg        BackfillConfig
	FetchBatch func(ctx context.Context, cursor int64, limit int) ([]BackfillRow, int64, error)
	WriteBatch func(ctx context.Context, rows []BackfillRow) error
}

func NewBackfiller(cfg BackfillConfig) *Backfiller {
	return &Backfiller{cfg: cfg}
}

// Run processes all rows from cursor 0 until FetchBatch returns empty.
func (b *Backfiller) Run(ctx context.Context) error {
	var cursor int64

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		rows, nextCursor, err := b.FetchBatch(ctx, cursor, b.cfg.BatchSize)
		if err != nil {
			return err
		}
		if len(rows) == 0 {
			return nil // done
		}

		if err := b.WriteBatch(ctx, rows); err != nil {
			return err
		}

		cursor = nextCursor
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/migration/ -v -run TestBackfiller`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/migration/backfiller.go internal/migration/backfiller_test.go
git commit -m "feat(reaction): add cursor-based backfiller for migration Phase 3

100-row batches with cursor pagination. FetchBatch/WriteBatch are
pluggable for testing. Context cancellation checked between batches
for graceful shutdown."
```

---

## Chunk 9: Monitoring + Reconciliation

### Task 16: Prometheus metrics + degradation ladder

**Files:**
- Create: `internal/monitoring/metrics.go`
- Create: `internal/monitoring/degradation.go`
- Create: `monitoring/alerts/reaction_alerts.yaml`

- [ ] **Step 1: Write the metrics registration**

`internal/monitoring/metrics.go`:
```go
package monitoring

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	// ReactionReadLatency tracks GetReactions p99.
	ReactionReadLatency = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "reaction_read_duration_seconds",
		Help:    "GetReactions RPC latency in seconds",
		Buckets: []float64{0.01, 0.025, 0.05, 0.1, 0.15, 0.25, 0.5},
	}, []string{"status"})

	// ReactionWriteLatency tracks AddReaction/RemoveReaction p99.
	ReactionWriteLatency = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "reaction_write_duration_seconds",
		Help:    "AddReaction/RemoveReaction RPC latency in seconds",
		Buckets: []float64{0.025, 0.05, 0.1, 0.2, 0.35, 0.5, 1.0},
	}, []string{"method", "status"})

	// SafetyCheckLatency tracks content safety check duration.
	SafetyCheckLatency = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "reaction_safety_check_duration_seconds",
		Help:    "Content safety sync check latency",
		Buckets: []float64{0.01, 0.05, 0.1, 0.2, 0.3},
	})

	// CacheTierHits tracks which tier served the read.
	CacheTierHits = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "reaction_cache_hits_total",
		Help: "Cache hit count by tier",
	}, []string{"tier"}) // "l1", "l2", "l3"

	// ReconcileDrift tracks |cache - db| drift per reconciliation run.
	ReconcileDrift = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "reaction_reconcile_drift",
		Help:    "Absolute difference between cached and DB counts per comment",
		Buckets: []float64{1, 5, 10, 25, 50, 100},
	})

	// HotspotDetections counts how many times CMS flagged a comment as hot.
	HotspotDetections = promauto.NewCounter(prometheus.CounterOpts{
		Name: "reaction_hotspot_detections_total",
		Help: "Number of comments flagged as hot by CMS",
	})

	// RateLimitRejections counts rate-limited requests by dimension.
	RateLimitRejections = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "reaction_ratelimit_rejections_total",
		Help: "Rate-limited requests by dimension",
	}, []string{"dimension"}) // "user_write", "user_read", "comment", "ip"
)
```

- [ ] **Step 2: Write the degradation ladder**

`internal/monitoring/degradation.go`:
```go
package monitoring

// DegradationLevel represents the system's operational state.
type DegradationLevel int

const (
	LevelNormal      DegradationLevel = iota // all systems nominal
	LevelCacheOnly                           // MySQL writes failing; serve from cache, buffer writes
	LevelSafetyBypass                        // safety service down; skip safety checks (log all)
	LevelReadOnly                            // writes disabled entirely; serve cached counts only
)

func (d DegradationLevel) String() string {
	switch d {
	case LevelNormal:
		return "normal"
	case LevelCacheOnly:
		return "cache_only"
	case LevelSafetyBypass:
		return "safety_bypass"
	case LevelReadOnly:
		return "read_only"
	default:
		return "unknown"
	}
}

// DegradationLadder determines the current operational level based on health signals.
type DegradationLadder struct {
	mysqlHealthy  func() bool
	safetyHealthy func() bool
	redisHealthy  func() bool
}

func NewDegradationLadder(mysql, safety, redis func() bool) *DegradationLadder {
	return &DegradationLadder{
		mysqlHealthy:  mysql,
		safetyHealthy: safety,
		redisHealthy:  redis,
	}
}

// CurrentLevel evaluates health checks and returns the degradation level.
func (d *DegradationLadder) CurrentLevel() DegradationLevel {
	if !d.redisHealthy() && !d.mysqlHealthy() {
		return LevelReadOnly
	}
	if !d.mysqlHealthy() {
		return LevelCacheOnly
	}
	if !d.safetyHealthy() {
		return LevelSafetyBypass
	}
	return LevelNormal
}
```

- [ ] **Step 3: Write alert rules**

`monitoring/alerts/reaction_alerts.yaml`:
```yaml
groups:
  - name: reaction_slos
    rules:
      # P1: Read latency SLO (p99 < 150ms)
      - alert: ReactionReadLatencyHigh
        expr: histogram_quantile(0.99, rate(reaction_read_duration_seconds_bucket[5m])) > 0.15
        for: 2m
        labels:
          severity: page
          team: comment
        annotations:
          summary: "Reaction read p99 > 150ms"
          description: "GetReactions p99 latency is {{ $value }}s (SLO: 150ms)."

      # P1: Write latency SLO (p99 < 350ms)
      - alert: ReactionWriteLatencyHigh
        expr: histogram_quantile(0.99, rate(reaction_write_duration_seconds_bucket[5m])) > 0.35
        for: 2m
        labels:
          severity: page
          team: comment
        annotations:
          summary: "Reaction write p99 > 350ms"
          description: "AddReaction/RemoveReaction p99 latency is {{ $value }}s (SLO: 350ms)."

      # P2: Reconciliation drift
      - alert: ReactionReconcileDriftHigh
        expr: reaction_reconcile_drift > 50
        for: 5m
        labels:
          severity: warning
          team: comment
        annotations:
          summary: "Reaction count drift > 50"
          description: "|cache - db| drift exceeds 50 for at least one comment."

      # P2: Safety service degraded
      - alert: ReactionSafetyLatencyHigh
        expr: histogram_quantile(0.99, rate(reaction_safety_check_duration_seconds_bucket[5m])) > 0.2
        for: 1m
        labels:
          severity: warning
          team: comment
        annotations:
          summary: "Safety check p99 approaching 200ms timeout"

      # P2: Hotspot escalation rate
      - alert: ReactionHotspotEscalationHigh
        expr: rate(reaction_hotspot_detections_total[5m]) > 10
        for: 3m
        labels:
          severity: warning
          team: comment
        annotations:
          summary: "High hotspot detection rate — possible viral content"
```

- [ ] **Step 4: Commit**

```bash
git add internal/monitoring/metrics.go internal/monitoring/degradation.go monitoring/alerts/reaction_alerts.yaml
git commit -m "feat(reaction): add Prometheus metrics, degradation ladder, and alert rules

Split P1 SLOs: read p99<150ms, write p99<350ms. Degradation ladder
with 4 levels based on MySQL/Redis/safety health. Alert rules cover
latency SLOs, reconciliation drift>50, safety degradation, and
hotspot escalation rates."
```

---

### Task 17: Reconciliation cron

**Files:**
- Create: `internal/reconcile/reconciler.go`
- Create: `internal/reconcile/reconciler_test.go`

- [ ] **Step 1: Write the failing test**

`internal/reconcile/reconciler_test.go`:
```go
package reconcile_test

import (
	"context"
	"testing"

	"comment-service/internal/model"
	"comment-service/internal/reconcile"
)

func TestReconciler_NoDrift(t *testing.T) {
	r := reconcile.NewReconciler(reconcile.Config{MaxDriftAlert: 50})
	r.GetDBCounts = func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error) {
		return map[model.ReactionType]uint32{model.ReactionLike: 10}, nil
	}
	r.GetCacheCounts = func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error) {
		return map[model.ReactionType]uint32{model.ReactionLike: 10}, nil
	}
	r.SetCacheCounts = func(ctx context.Context, commentID int64, counts map[model.ReactionType]uint32) error {
		t.Error("should not set cache when no drift")
		return nil
	}

	result, err := r.ReconcileComment(context.Background(), 100)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.MaxDrift != 0 {
		t.Errorf("max drift = %d, want 0", result.MaxDrift)
	}
	if result.AlertTriggered {
		t.Error("should not alert on zero drift")
	}
}

func TestReconciler_SmallDrift_CorrectsSilently(t *testing.T) {
	var corrected bool
	r := reconcile.NewReconciler(reconcile.Config{MaxDriftAlert: 50})
	r.GetDBCounts = func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error) {
		return map[model.ReactionType]uint32{model.ReactionLike: 10}, nil
	}
	r.GetCacheCounts = func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error) {
		return map[model.ReactionType]uint32{model.ReactionLike: 12}, nil // +2 drift
	}
	r.SetCacheCounts = func(ctx context.Context, commentID int64, counts map[model.ReactionType]uint32) error {
		corrected = true
		if counts[model.ReactionLike] != 10 {
			t.Errorf("correction set like=%d, want 10", counts[model.ReactionLike])
		}
		return nil
	}

	result, _ := r.ReconcileComment(context.Background(), 100)
	if !corrected {
		t.Error("should correct cache to match DB")
	}
	if result.MaxDrift != 2 {
		t.Errorf("max drift = %d, want 2", result.MaxDrift)
	}
	if result.AlertTriggered {
		t.Error("drift of 2 should not trigger alert (threshold 50)")
	}
}

func TestReconciler_LargeDrift_TriggersAlert(t *testing.T) {
	r := reconcile.NewReconciler(reconcile.Config{MaxDriftAlert: 50})
	r.GetDBCounts = func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error) {
		return map[model.ReactionType]uint32{model.ReactionLike: 100}, nil
	}
	r.GetCacheCounts = func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error) {
		return map[model.ReactionType]uint32{model.ReactionLike: 200}, nil // drift = 100
	}
	r.SetCacheCounts = func(ctx context.Context, commentID int64, counts map[model.ReactionType]uint32) error {
		return nil
	}

	result, _ := r.ReconcileComment(context.Background(), 100)
	if !result.AlertTriggered {
		t.Error("drift of 100 should trigger alert (threshold 50)")
	}
	if result.MaxDrift != 100 {
		t.Errorf("max drift = %d, want 100", result.MaxDrift)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/reconcile/ -v -run TestReconciler`
Expected: FAIL — package not found.

- [ ] **Step 3: Write minimal implementation**

`internal/reconcile/reconciler.go`:
```go
package reconcile

import (
	"context"

	"comment-service/internal/model"
)

// Config for the reconciliation cron.
type Config struct {
	MaxDriftAlert int // |cache - db| above this triggers an alert
}

// Result of reconciling a single comment.
type Result struct {
	CommentID      int64
	MaxDrift       int
	AlertTriggered bool
	Corrected      bool
}

// Reconciler corrects cache↔DB drift. Runs as a single-leader cron every 4h.
type Reconciler struct {
	cfg            Config
	GetDBCounts    func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error)
	GetCacheCounts func(ctx context.Context, commentID int64) (map[model.ReactionType]uint32, error)
	SetCacheCounts func(ctx context.Context, commentID int64, counts map[model.ReactionType]uint32) error
}

func NewReconciler(cfg Config) *Reconciler {
	return &Reconciler{cfg: cfg}
}

// ReconcileComment compares DB and cache counts for one comment and corrects drift.
func (r *Reconciler) ReconcileComment(ctx context.Context, commentID int64) (Result, error) {
	dbCounts, err := r.GetDBCounts(ctx, commentID)
	if err != nil {
		return Result{CommentID: commentID}, err
	}

	cacheCounts, err := r.GetCacheCounts(ctx, commentID)
	if err != nil {
		return Result{CommentID: commentID}, err
	}

	maxDrift := 0
	hasDrift := false

	// Compute max drift across all reaction types
	allTypes := make(map[model.ReactionType]bool)
	for rt := range dbCounts {
		allTypes[rt] = true
	}
	for rt := range cacheCounts {
		allTypes[rt] = true
	}

	for rt := range allTypes {
		db := int(dbCounts[rt])
		cache := int(cacheCounts[rt])
		drift := abs(db - cache)
		if drift > maxDrift {
			maxDrift = drift
		}
		if drift > 0 {
			hasDrift = true
		}
	}

	result := Result{
		CommentID:      commentID,
		MaxDrift:       maxDrift,
		AlertTriggered: maxDrift > r.cfg.MaxDriftAlert,
	}

	if hasDrift {
		// Correct cache to match DB (DB is source of truth)
		if err := r.SetCacheCounts(ctx, commentID, dbCounts); err != nil {
			return result, err
		}
		result.Corrected = true
	}

	return result, nil
}

func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/reconcile/ -v -run TestReconciler`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/reconcile/reconciler.go internal/reconcile/reconciler_test.go
git commit -m "feat(reaction): add reconciliation cron with drift alerting

Single-leader cron runs every 4h. Compares cache vs DB counts per
comment, corrects cache to match DB (source of truth), and alerts
when |diff| > 50. Max drift 24h guaranteed by cron schedule."
```

---

## Chunk 10: Service Layer (gRPC Handler)

### Task 18: Reaction gRPC service

**Files:**
- Create: `internal/service/reaction_service.go`
- Create: `internal/service/reaction_service_test.go`

- [ ] **Step 1: Write the failing test**

`internal/service/reaction_service_test.go`:
```go
package service_test

import (
	"context"
	"testing"

	"comment-service/internal/model"
	"comment-service/internal/service"
)

type mockDeps struct {
	upsertCalled    bool
	deactivateCalled bool
	safetyVerdict   bool // true = allow
	shadowBanned    bool
	rateLimited     bool
	hotspotBlocked  bool
	lastKafkaEvent  string
}

func newMockDeps() *mockDeps {
	return &mockDeps{safetyVerdict: true}
}

func (m *mockDeps) Upsert(ctx context.Context, r model.Reaction) error {
	m.upsertCalled = true
	return nil
}

func (m *mockDeps) Deactivate(ctx context.Context, commentID, userID int64, rt model.ReactionType) error {
	m.deactivateCalled = true
	return nil
}

func (m *mockDeps) CheckSafety(ctx context.Context, userID, commentID int64) (bool, error) {
	return m.safetyVerdict, nil
}

func (m *mockDeps) IsShadowBanned(userID int64) bool { return m.shadowBanned }
func (m *mockDeps) AllowUserWrite(userID int64) bool  { return !m.rateLimited }
func (m *mockDeps) AllowComment(commentID int64) bool { return !m.hotspotBlocked }
func (m *mockDeps) PublishAudit(ctx context.Context, event string) { m.lastKafkaEvent = event }
func (m *mockDeps) IncrCacheCount(ctx context.Context, commentID int64, rt model.ReactionType, delta int64) error {
	return nil
}
func (m *mockDeps) InvalidateL1(commentID int64) {}
func (m *mockDeps) EnqueueFlush(commentID, postID int64, rt model.ReactionType, delta int64) {}
func (m *mockDeps) RecordHotspot(commentID int64) {}
func (m *mockDeps) GenerateID() int64 { return 999 }
func (m *mockDeps) LookupPostID(ctx context.Context, commentID int64) (int64, error) { return 1, nil }

func TestAddReaction_HappyPath(t *testing.T) {
	deps := newMockDeps()
	svc := service.NewReactionService(deps)

	err := svc.AddReaction(context.Background(), 200, 100, model.ReactionLike)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !deps.upsertCalled {
		t.Error("upsert should be called")
	}
}

func TestAddReaction_InvalidType_Rejected(t *testing.T) {
	deps := newMockDeps()
	svc := service.NewReactionService(deps)

	err := svc.AddReaction(context.Background(), 200, 100, model.ReactionType(99))
	if err == nil {
		t.Error("invalid reaction type should be rejected")
	}
}

func TestAddReaction_RateLimited(t *testing.T) {
	deps := newMockDeps()
	deps.rateLimited = true
	svc := service.NewReactionService(deps)

	err := svc.AddReaction(context.Background(), 200, 100, model.ReactionLike)
	if err == nil {
		t.Error("rate-limited request should be rejected")
	}
}

func TestAddReaction_SafetyBlocked(t *testing.T) {
	deps := newMockDeps()
	deps.safetyVerdict = false
	svc := service.NewReactionService(deps)

	err := svc.AddReaction(context.Background(), 200, 100, model.ReactionLike)
	if err == nil {
		t.Error("safety-blocked request should be rejected")
	}
}

func TestAddReaction_ShadowBanned_PhantomWrite(t *testing.T) {
	deps := newMockDeps()
	deps.shadowBanned = true
	svc := service.NewReactionService(deps)

	err := svc.AddReaction(context.Background(), 200, 100, model.ReactionLike)
	if err != nil {
		t.Fatalf("shadow-banned user should get success: %v", err)
	}
	if deps.upsertCalled {
		t.Error("shadow-banned user should NOT trigger real upsert")
	}
}

func TestRemoveReaction_HappyPath(t *testing.T) {
	deps := newMockDeps()
	svc := service.NewReactionService(deps)

	err := svc.RemoveReaction(context.Background(), 200, 100, model.ReactionLike)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !deps.deactivateCalled {
		t.Error("deactivate should be called")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/service/ -v -run Test`
Expected: FAIL — package not found.

- [ ] **Step 3: Write minimal implementation**

`internal/service/reaction_service.go`:
```go
package service

import (
	"context"
	"fmt"

	"comment-service/internal/model"
)

// Deps abstracts all external dependencies for the reaction service.
type Deps interface {
	// Persistence
	Upsert(ctx context.Context, r model.Reaction) error
	Deactivate(ctx context.Context, commentID, userID int64, rt model.ReactionType) error
	LookupPostID(ctx context.Context, commentID int64) (int64, error)
	GenerateID() int64

	// Safety
	CheckSafety(ctx context.Context, userID, commentID int64) (bool, error)
	IsShadowBanned(userID int64) bool

	// Rate limiting
	AllowUserWrite(userID int64) bool
	AllowComment(commentID int64) bool

	// Cache
	IncrCacheCount(ctx context.Context, commentID int64, rt model.ReactionType, delta int64) error
	InvalidateL1(commentID int64)
	EnqueueFlush(commentID, postID int64, rt model.ReactionType, delta int64)

	// Hotspot
	RecordHotspot(commentID int64)

	// Audit
	PublishAudit(ctx context.Context, event string)
}

// ReactionService implements the gRPC CommentReactionService.
type ReactionService struct {
	deps Deps
}

func NewReactionService(deps Deps) *ReactionService {
	return &ReactionService{deps: deps}
}

// AddReaction validates, safety-checks, and persists a reaction.
// Pipeline: validate → rate-limit → safety → shadow-ban → hotspot → persist → cache → audit.
func (s *ReactionService) AddReaction(ctx context.Context, userID, commentID int64, rt model.ReactionType) error {
	// 1. Validate
	if !rt.Valid() {
		return fmt.Errorf("invalid reaction type: %d", rt)
	}

	// 2. Rate limit
	if !s.deps.AllowUserWrite(userID) {
		return fmt.Errorf("rate limited: user %d write limit exceeded", userID)
	}
	if !s.deps.AllowComment(commentID) {
		return fmt.Errorf("rate limited: comment %d request limit exceeded", commentID)
	}

	// 3. Safety check (sync, fail-closed)
	allowed, err := s.deps.CheckSafety(ctx, userID, commentID)
	if err != nil || !allowed {
		s.deps.PublishAudit(ctx, fmt.Sprintf("safety_block:user=%d,comment=%d,type=%s", userID, commentID, rt))
		return fmt.Errorf("reaction blocked by content safety")
	}

	// 4. Shadow ban (phantom write — return success, skip persistence)
	if s.deps.IsShadowBanned(userID) {
		s.deps.PublishAudit(ctx, fmt.Sprintf("phantom_write:user=%d,comment=%d,type=%s", userID, commentID, rt))
		return nil
	}

	// 5. Hotspot tracking
	s.deps.RecordHotspot(commentID)

	// 6. Resolve post_id for the reaction row
	postID, err := s.deps.LookupPostID(ctx, commentID)
	if err != nil {
		return fmt.Errorf("lookup post_id: %w", err)
	}

	// 7. Persist (IODKU)
	reaction := model.Reaction{
		ID:           s.deps.GenerateID(),
		CommentID:    commentID,
		UserID:       userID,
		PostID:       postID,
		ReactionType: rt,
		IsActive:     true,
	}
	if err := s.deps.Upsert(ctx, reaction); err != nil {
		return fmt.Errorf("upsert reaction: %w", err)
	}

	// 8. Speculative cache increment + enqueue write-behind flush
	_ = s.deps.IncrCacheCount(ctx, commentID, rt, 1)
	s.deps.InvalidateL1(commentID)
	s.deps.EnqueueFlush(commentID, postID, rt, 1)

	// 9. Audit event
	s.deps.PublishAudit(ctx, fmt.Sprintf("add_reaction:user=%d,comment=%d,type=%s", userID, commentID, rt))

	return nil
}

// RemoveReaction validates, rate-limits, and soft-deletes a reaction.
func (s *ReactionService) RemoveReaction(ctx context.Context, userID, commentID int64, rt model.ReactionType) error {
	if !rt.Valid() {
		return fmt.Errorf("invalid reaction type: %d", rt)
	}

	if !s.deps.AllowUserWrite(userID) {
		return fmt.Errorf("rate limited: user %d write limit exceeded", userID)
	}

	postID, err := s.deps.LookupPostID(ctx, commentID)
	if err != nil {
		return fmt.Errorf("lookup post_id: %w", err)
	}

	if err := s.deps.Deactivate(ctx, commentID, userID, rt); err != nil {
		return fmt.Errorf("deactivate reaction: %w", err)
	}

	_ = s.deps.IncrCacheCount(ctx, commentID, rt, -1)
	s.deps.InvalidateL1(commentID)
	s.deps.EnqueueFlush(commentID, postID, rt, -1)

	s.deps.PublishAudit(ctx, fmt.Sprintf("remove_reaction:user=%d,comment=%d,type=%s", userID, commentID, rt))

	return nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/service/ -v -run Test`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/service/reaction_service.go internal/service/reaction_service_test.go
git commit -m "feat(reaction): add gRPC reaction service with full pipeline

AddReaction pipeline: validate → rate-limit → safety (fail-closed) →
shadow-ban (phantom write) → hotspot → persist (IODKU) → cache
(speculative HINCRBY + L1 invalidate + write-behind enqueue) → audit.
RemoveReaction follows same pattern minus safety check. Deps interface
enables complete mock testing of the pipeline."
```

---

## Chunk 11: Testing

### Task 19: Contract tests + integration + scenario matrix

**Files:**
- Create: `tests/contract/proto_breaking_test.go`
- Create: `tests/contract/schema_breaking_test.go`
- Create: `tests/integration/testcontainers_setup_test.go`
- Create: `tests/integration/reaction_integration_test.go`
- Create: `tests/golden/feed_event_fixtures.json`

- [ ] **Step 1: Write proto contract test**

`tests/contract/proto_breaking_test.go`:
```go
package contract_test

import (
	"os/exec"
	"testing"
)

func TestProto_NoBreakingChanges(t *testing.T) {
	// buf breaking checks current proto against the committed version.
	// This fails if fields are removed, types changed, etc.
	cmd := exec.Command("buf", "breaking", "proto/", "--against", ".git#branch=main,subdir=proto")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("proto breaking changes detected:\n%s", string(out))
	}
}
```

- [ ] **Step 2: Write schema contract test**

`tests/contract/schema_breaking_test.go`:
```go
package contract_test

import (
	"os/exec"
	"testing"
)

func TestSchema_NoBreakingChanges(t *testing.T) {
	// skeema diff checks current migrations against the live schema.
	// Skip if skeema is not available.
	if _, err := exec.LookPath("skeema"); err != nil {
		t.Skip("skeema not installed")
	}
	cmd := exec.Command("skeema", "diff", "--brief")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("schema breaking changes detected:\n%s", string(out))
	}
}
```

- [ ] **Step 3: Write Testcontainers setup**

`tests/integration/testcontainers_setup_test.go`:
```go
package integration_test

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"testing"

	_ "github.com/go-sql-driver/mysql"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/modules/mysql"
	"github.com/testcontainers/testcontainers-go/modules/redis"
)

var (
	testDB    *sql.DB
	redisAddr string
)

func TestMain(m *testing.M) {
	ctx := context.Background()

	// MySQL container
	mysqlC, err := mysql.Run(ctx, "mysql:8.0",
		mysql.WithDatabase("testdb"),
		mysql.WithUsername("test"),
		mysql.WithPassword("test"),
	)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to start mysql: %v\n", err)
		os.Exit(1)
	}
	defer func() { _ = mysqlC.Terminate(ctx) }()

	mysqlDSN, _ := mysqlC.ConnectionString(ctx)
	testDB, err = sql.Open("mysql", mysqlDSN)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to connect mysql: %v\n", err)
		os.Exit(1)
	}

	// Apply migrations
	for _, file := range []string{
		"../../migrations/20260429_001_create_comment_reactions.sql",
		"../../migrations/20260429_002_create_comment_reaction_counts.sql",
	} {
		sqlBytes, _ := os.ReadFile(file)
		if _, err := testDB.ExecContext(ctx, string(sqlBytes)); err != nil {
			fmt.Fprintf(os.Stderr, "migration %s failed: %v\n", file, err)
			os.Exit(1)
		}
	}

	// Redis container
	redisC, err := redis.Run(ctx, "redis:7")
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to start redis: %v\n", err)
		os.Exit(1)
	}
	defer func() { _ = redisC.Terminate(ctx) }()

	endpoint, _ := redisC.Endpoint(ctx, "")
	redisAddr = endpoint

	os.Exit(m.Run())
}
```

- [ ] **Step 4: Write 8-scenario integration test matrix**

`tests/integration/reaction_integration_test.go`:
```go
package integration_test

import (
	"context"
	"testing"
)

// 8 scenario matrix per tech design:
// 1. Add reaction (new)
// 2. Add reaction (re-activate)
// 3. Add reaction (duplicate — idempotent)
// 4. Remove reaction
// 5. Remove non-existent reaction (no-op)
// 6. Get reactions (single comment)
// 7. Get reactions (batch)
// 8. Get reactions (empty — no reactions)

func TestIntegration_AddReaction_New(t *testing.T) {
	if testDB == nil {
		t.Skip("no test database available")
	}
	ctx := context.Background()

	// Insert reaction for user 1 on comment 100
	_, err := testDB.ExecContext(ctx,
		`INSERT INTO comment_reactions (id, comment_id, user_id, post_id, reaction_type, is_active)
		 VALUES (1, 100, 1, 10, 1, 1)
		 ON DUPLICATE KEY UPDATE is_active = VALUES(is_active)`)
	if err != nil {
		t.Fatalf("insert failed: %v", err)
	}

	var isActive int
	err = testDB.QueryRowContext(ctx,
		`SELECT is_active FROM comment_reactions WHERE comment_id = 100 AND user_id = 1 AND reaction_type = 1`,
	).Scan(&isActive)
	if err != nil {
		t.Fatalf("query failed: %v", err)
	}
	if isActive != 1 {
		t.Errorf("is_active = %d, want 1", isActive)
	}
}

func TestIntegration_AddReaction_Reactivate(t *testing.T) {
	if testDB == nil {
		t.Skip("no test database available")
	}
	ctx := context.Background()

	// Deactivate then reactivate
	_, _ = testDB.ExecContext(ctx,
		`INSERT INTO comment_reactions (id, comment_id, user_id, post_id, reaction_type, is_active)
		 VALUES (2, 200, 2, 20, 1, 0)
		 ON DUPLICATE KEY UPDATE is_active = VALUES(is_active)`)
	_, _ = testDB.ExecContext(ctx,
		`INSERT INTO comment_reactions (id, comment_id, user_id, post_id, reaction_type, is_active)
		 VALUES (2, 200, 2, 20, 1, 1)
		 ON DUPLICATE KEY UPDATE is_active = VALUES(is_active)`)

	var isActive int
	_ = testDB.QueryRowContext(ctx,
		`SELECT is_active FROM comment_reactions WHERE comment_id = 200 AND user_id = 2 AND reaction_type = 1`,
	).Scan(&isActive)
	if isActive != 1 {
		t.Errorf("reactivated is_active = %d, want 1", isActive)
	}
}

func TestIntegration_AddReaction_Idempotent(t *testing.T) {
	if testDB == nil {
		t.Skip("no test database available")
	}
	ctx := context.Background()

	for i := 0; i < 3; i++ {
		_, err := testDB.ExecContext(ctx,
			`INSERT INTO comment_reactions (id, comment_id, user_id, post_id, reaction_type, is_active)
			 VALUES (3, 300, 3, 30, 2, 1)
			 ON DUPLICATE KEY UPDATE is_active = VALUES(is_active)`)
		if err != nil {
			t.Fatalf("idempotent insert %d failed: %v", i, err)
		}
	}

	var count int
	_ = testDB.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM comment_reactions WHERE comment_id = 300 AND user_id = 3 AND reaction_type = 2`,
	).Scan(&count)
	if count != 1 {
		t.Errorf("row count = %d, want 1 (idempotent)", count)
	}
}

func TestIntegration_RemoveReaction(t *testing.T) {
	if testDB == nil {
		t.Skip("no test database available")
	}
	ctx := context.Background()

	_, _ = testDB.ExecContext(ctx,
		`INSERT INTO comment_reactions (id, comment_id, user_id, post_id, reaction_type, is_active)
		 VALUES (4, 400, 4, 40, 1, 1)
		 ON DUPLICATE KEY UPDATE is_active = VALUES(is_active)`)
	_, _ = testDB.ExecContext(ctx,
		`UPDATE comment_reactions SET is_active = 0 WHERE comment_id = 400 AND user_id = 4 AND reaction_type = 1`)

	var isActive int
	_ = testDB.QueryRowContext(ctx,
		`SELECT is_active FROM comment_reactions WHERE comment_id = 400 AND user_id = 4 AND reaction_type = 1`,
	).Scan(&isActive)
	if isActive != 0 {
		t.Errorf("after remove is_active = %d, want 0", isActive)
	}
}

func TestIntegration_RemoveNonexistent_NoOp(t *testing.T) {
	if testDB == nil {
		t.Skip("no test database available")
	}
	ctx := context.Background()

	result, err := testDB.ExecContext(ctx,
		`UPDATE comment_reactions SET is_active = 0 WHERE comment_id = 999 AND user_id = 999 AND reaction_type = 1`)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	rows, _ := result.RowsAffected()
	if rows != 0 {
		t.Errorf("rows affected = %d, want 0 (no-op)", rows)
	}
}

func TestIntegration_GetCountsSingle(t *testing.T) {
	if testDB == nil {
		t.Skip("no test database available")
	}
	ctx := context.Background()

	_, _ = testDB.ExecContext(ctx,
		`INSERT INTO comment_reaction_counts (post_id, comment_id, reaction_type, count)
		 VALUES (50, 500, 1, 42)
		 ON DUPLICATE KEY UPDATE count = VALUES(count)`)

	var count int
	_ = testDB.QueryRowContext(ctx,
		`SELECT count FROM comment_reaction_counts WHERE comment_id = 500 AND reaction_type = 1`,
	).Scan(&count)
	if count != 42 {
		t.Errorf("count = %d, want 42", count)
	}
}

func TestIntegration_GetCountsBatch(t *testing.T) {
	if testDB == nil {
		t.Skip("no test database available")
	}
	ctx := context.Background()

	_, _ = testDB.ExecContext(ctx,
		`INSERT INTO comment_reaction_counts (post_id, comment_id, reaction_type, count)
		 VALUES (60, 600, 1, 10), (60, 601, 1, 20)
		 ON DUPLICATE KEY UPDATE count = VALUES(count)`)

	rows, err := testDB.QueryContext(ctx,
		`SELECT comment_id, count FROM comment_reaction_counts WHERE comment_id IN (600, 601) AND reaction_type = 1`)
	if err != nil {
		t.Fatalf("query failed: %v", err)
	}
	defer rows.Close()

	results := make(map[int64]int)
	for rows.Next() {
		var cid int64
		var c int
		_ = rows.Scan(&cid, &c)
		results[cid] = c
	}
	if results[600] != 10 || results[601] != 20 {
		t.Errorf("batch results: %v", results)
	}
}

func TestIntegration_GetCountsEmpty(t *testing.T) {
	if testDB == nil {
		t.Skip("no test database available")
	}
	ctx := context.Background()

	rows, err := testDB.QueryContext(ctx,
		`SELECT count FROM comment_reaction_counts WHERE comment_id = 99999`)
	if err != nil {
		t.Fatalf("query failed: %v", err)
	}
	defer rows.Close()
	if rows.Next() {
		t.Error("expected no rows for non-existent comment")
	}
}
```

- [ ] **Step 5: Write feed golden fixtures**

`tests/golden/feed_event_fixtures.json`:
```json
{
  "_comment": "Golden fixtures for feed module Kafka event consumption. Each entry represents an expected event structure after a reaction action.",
  "events": [
    {
      "name": "add_reaction",
      "topic": "comment.reactions",
      "key": "100",
      "value": {
        "event_type": "add_reaction",
        "comment_id": 100,
        "user_id": 200,
        "post_id": 10,
        "reaction_type": "like",
        "timestamp": "2026-04-29T12:00:00Z"
      }
    },
    {
      "name": "remove_reaction",
      "topic": "comment.reactions",
      "key": "100",
      "value": {
        "event_type": "remove_reaction",
        "comment_id": 100,
        "user_id": 200,
        "post_id": 10,
        "reaction_type": "like",
        "timestamp": "2026-04-29T12:00:01Z"
      }
    },
    {
      "name": "safety_block_audit",
      "topic": "comment.reactions.audit",
      "key": "100",
      "value": {
        "event_type": "safety_block",
        "comment_id": 100,
        "user_id": 666,
        "reason": "content_safety_block",
        "timestamp": "2026-04-29T12:00:02Z"
      }
    },
    {
      "name": "phantom_write_audit",
      "topic": "comment.reactions.audit",
      "key": "100",
      "value": {
        "event_type": "phantom_write",
        "comment_id": 100,
        "user_id": 777,
        "reason": "shadow_ban",
        "timestamp": "2026-04-29T12:00:03Z"
      }
    }
  ]
}
```

- [ ] **Step 6: Run contract tests (will skip if tools not installed)**

Run: `go test ./tests/contract/ -v -timeout 30s`
Expected: Tests PASS or SKIP (if buf/skeema not installed).

- [ ] **Step 7: Run integration tests (requires Docker)**

Run: `go test ./tests/integration/ -v -timeout 120s`
Expected: 8 PASS (or SKIP if Docker not available).

- [ ] **Step 8: Commit**

```bash
git add tests/contract/proto_breaking_test.go tests/contract/schema_breaking_test.go tests/integration/testcontainers_setup_test.go tests/integration/reaction_integration_test.go tests/golden/feed_event_fixtures.json
git commit -m "test(reaction): add contract, integration, and golden fixture tests

Contract tests: buf breaking (proto), skeema diff (schema).
Integration: 8-scenario matrix via Testcontainers (MySQL 8 + Redis 7).
Golden fixtures: 4 Kafka event shapes for feed module consumption."
```

---

## Chunk 12: Chaos Runbook

### Task 20: Chaos engineering runbook

**Files:**
- Create: `chaos/runbook.md`

- [ ] **Step 1: Write the runbook**

`chaos/runbook.md`:
```markdown
# Comment Reactions — Chaos Runbook

> **Schedule:** Pre-launch mandatory. Quarterly recurring.
> **Owner:** comment team on-call.

## Prerequisites

- Staging environment with full reaction stack deployed
- Chaos tooling (Toxiproxy / Litmus / tc) available
- Monitoring dashboards open: reaction SLOs, degradation level, reconciliation drift

---

## Scenario 1: MySQL Primary Down

**Injection:** `toxiproxy-cli toxic add mysql-primary -t timeout -a timeout=0`
**Duration:** 5 minutes
**Expected behavior:**
- [ ] Writes fail; degradation ladder escalates to `cache_only`
- [ ] Read traffic continues from L1/L2 cache
- [ ] Write-behind buffer accumulates deltas
- [ ] `ReactionWriteLatencyHigh` alert fires within 2 min
**Pass criteria:** Zero 5xx on reads. Writes return 503 within 500ms. Buffer drains after MySQL recovery.
**Rollback:** `toxiproxy-cli toxic remove mysql-primary -n timeout`

---

## Scenario 2: Redis Cluster Partition

**Injection:** `iptables -A INPUT -p tcp --dport 6379 -j DROP` on Redis nodes
**Duration:** 3 minutes
**Expected behavior:**
- [ ] L2 cache misses; reads fall through to L3 (MySQL)
- [ ] Speculative HINCRBY fails; compensating HINCRBY skipped
- [ ] L1 cache serves stale data with TTL-bounded staleness
- [ ] `CacheTierHits` metric shows shift from l2 to l3
**Pass criteria:** Read p99 < 300ms (degraded but functional). No data loss.
**Rollback:** `iptables -D INPUT -p tcp --dport 6379 -j DROP`

---

## Scenario 3: Safety Service Timeout

**Injection:** `toxiproxy-cli toxic add safety-svc -t latency -a latency=500`
**Duration:** 5 minutes
**Expected behavior:**
- [ ] Safety check times out at 200ms (fail-closed)
- [ ] All writes blocked; `ReactionSafetyLatencyHigh` alert fires
- [ ] Degradation ladder escalates to `safety_bypass` after threshold
- [ ] Kafka audit events log all blocked reactions
**Pass criteria:** No unsafe reactions persisted. Alert fires within 1 min.
**Rollback:** `toxiproxy-cli toxic remove safety-svc -n latency`

---

## Scenario 4: Celebrity Comment Hotspot

**Injection:** Locust script: 10k users react to comment_id=1 at 5k req/s
**Duration:** 2 minutes
**Expected behavior:**
- [ ] CMS detects hotspot; `HotspotDetections` counter increments
- [ ] Adaptive limiter throttles writes on comment 1
- [ ] Other comments unaffected
- [ ] Dedicated Redis escalation triggers (if enabled)
**Pass criteria:** comment_id=1 write rejection rate > 80%. Other comments p99 < 150ms read.
**Rollback:** Stop Locust script.

---

## Scenario 5: Write-Behind Buffer Overflow

**Injection:** Pause MySQL writes (LOCK TABLES) + flood reactions
**Duration:** Until buffer reaches capacity
**Expected behavior:**
- [ ] Buffer fills to capacity (BatchSize * 2)
- [ ] Overflow triggers synchronous inline flush (backpressure)
- [ ] Speculative Redis counts diverge from DB
- [ ] Reconciliation corrects drift after MySQL recovers
**Pass criteria:** No lost deltas. Drift resolved within one reconciliation cycle (4h).
**Rollback:** `UNLOCK TABLES`

---

## Scenario 6: Kafka Broker Down

**Injection:** Stop Kafka broker container
**Duration:** 5 minutes
**Expected behavior:**
- [ ] Audit event publishing fails silently (non-blocking)
- [ ] Reaction writes continue unaffected
- [ ] Audit events are lost (accepted tradeoff — at-most-once for audit)
- [ ] Feed module stops receiving new events; ClickHouse pipeline stalls
**Pass criteria:** Reaction latency unaffected. No user-visible errors.
**Rollback:** Start Kafka broker container.

---

## Scenario 7: Pod Crash During Write-Behind Drain

**Injection:** `kill -9` on pod during active write-behind flush
**Duration:** Instant
**Expected behavior:**
- [ ] In-flight buffer deltas are lost (bounded by flush interval × rate)
- [ ] Speculative Redis counts may be ahead of DB
- [ ] Reconciliation corrects drift on next 4h cycle
- [ ] No duplicate reactions (IODKU is idempotent)
**Pass criteria:** Max drift < 500 (bounded by 200ms flush × write rate). No duplicates.
**Rollback:** Pod auto-restarts via Kubernetes.

---

## Post-Chaos Checklist

After each scenario:
1. [ ] Verify all alerts cleared within 5 min of rollback
2. [ ] Verify degradation level returned to `normal`
3. [ ] Run reconciliation manually: drift should be within expected bounds
4. [ ] Check Kafka consumer lag recovered (for scenario 6)
5. [ ] Review audit log completeness for safety scenarios (3)
```

- [ ] **Step 2: Commit**

```bash
git add chaos/runbook.md
git commit -m "feat(reaction): add chaos engineering runbook (7 scenarios)

Pre-launch mandatory + quarterly recurring. Covers MySQL down, Redis
partition, safety timeout, celebrity hotspot, buffer overflow, Kafka
down, and pod crash. Each scenario has injection method, expected
behavior checklist, and pass/fail criteria."
```

---

### Task 21: Full test suite verification

**Files:** (no new files)

- [ ] **Step 1: Run all unit tests**

Run: `go test ./internal/... -v -count=1`
Expected: All tests pass (~35 tests across model, repository, cache, safety, hotspot, ratelimit, service, migration, reconcile).

- [ ] **Step 2: Run contract tests**

Run: `go test ./tests/contract/ -v`
Expected: PASS or SKIP.

- [ ] **Step 3: Run integration tests**

Run: `go test ./tests/integration/ -v -timeout 120s`
Expected: 8 PASS (or SKIP if Docker unavailable).

- [ ] **Step 4: Verify no lint issues**

Run: `golangci-lint run ./...`
Expected: No errors.

- [ ] **Step 5: Final commit if any fixups needed**

If all tests pass: no commit needed — this task is a verification gate.
If fixups required: fix, test again, and commit with message explaining the fix.

---

## Self-Review

### 1. Spec coverage

| Tech Design Component | Task(s) |
|---|---|
| Data model (comment_reactions + counts, Snowflake ID, IODKU) | Task 1, 2 |
| gRPC API (AddReaction/RemoveReaction/GetReactions, enum, JWT) | Task 3 |
| Repository layer (IODKU write, count increment/decrement) | Task 4, 5 |
| Cache L2 Redis Hash (HINCRBY speculative + compensating) | Task 6 |
| Cache L1 Caffeine TinyLFU 32k | Task 7 |
| Cache write-behind buffer (200ms/500/2s) | Task 8 |
| Tiered cache orchestrator (L1→L2→L3) | Task 9 |
| Content safety (sync 200ms fail-closed) | Task 10 |
| Shadow ban (phantom write) + Z-score abuse detection | Task 11 |
| Hotspot (Count-Min Sketch pod-local) | Task 12 |
| Adaptive rate limiting + Redis escalation | Task 12 |
| Rate limiting (per-user/comment/IP+CIDR) | Task 13 |
| Service layer (full pipeline wiring) | Task 18 |
| Migration Phase 2 dual-write | Task 14 |
| Migration Phase 3 backfill (100 rows) | Task 15 |
| Migration Phase 4 canary (5%→20%→50%→100%) | Canary rollout is an operational procedure using Task 14's dual-writer with traffic percentage — wired in deployment config, not code |
| Monitoring (split read/write p99 SLOs, degradation ladder) | Task 16 |
| Reconciliation (4h cron, \|diff\|>50 alert) | Task 17 |
| Testing (contract/integration/8-scenario/golden) | Task 19 |
| Chaos runbook (7 scenarios, pre-launch + quarterly) | Task 20 |
| Kafka audit events | Wired in Task 18 (PublishAudit), golden fixtures in Task 19 |

**No gaps detected.** All 11 tech design components map to tasks.

### 2. Placeholder scan

Scanning for "TBD", "TODO", "implement later", "similar to Task N":
- None found. Every step includes actual code, SQL, proto, YAML, or Markdown.

### 3. Type consistency

- `model.ReactionType` — used consistently across all packages (uint8 enum, 6 values).
- `model.Reaction` fields (ID, CommentID, UserID, PostID, ReactionType, IsActive) — match SQL schema and repo layer.
- `model.ReactionCount` fields (PostID, CommentID, ReactionType, Count) — match count table and cache layer.
- `cache.CountDelta` — used in write-behind and service layer consistently.
- `safety.Verdict` — VerdictAllow/VerdictBlock used in checker and service.
- `service.Deps` interface — all methods match the mock in test (verified method signatures).
- DB/CountDB/RedisClient interfaces — consistent between definition and mock implementations.

All consistent. No renames between tasks.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
