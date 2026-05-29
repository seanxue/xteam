# KB 更新候选

> Session: 2700e9a4-a773-476e-bc94-7d0c073fe786
> 生成于圆桌完成后，需人审后执行 `/xteam-writeback`

```yaml
session_id: 2700e9a4-a773-476e-bc94-7d0c073fe786
candidate_updates:
- type: new_adr
  scope: roundtable/round_1
  summary: Replaced deleted_at in unique index with is_active column. UK now (comment_id,
    user_id, reaction_type, is_active) correctly prevents duplicate active reactions.
  rationale: Round 1 data reviewer critical issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Added post_id to comment_reaction_counts, PK changed to (post_id, comment_id,
    reaction_type) for shard routing per ADR-0031.
  rationale: Round 1 data reviewer critical issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: 'Reordered migration: dual-write activates BEFORE backfill. Backfill uses
    INSERT IGNORE bounded by dual_write_start timestamp.'
  rationale: Round 1 data reviewer critical issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Replaced AUTO_INCREMENT with Snowflake distributed ID to avoid cross-shard
    ID collisions.
  rationale: Round 1 data reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Buffer persisted to Redis Sorted Set per-pod with leader election for crash
    recovery. Daily reconciliation guarantees eventual correctness.
  rationale: Round 1 data reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Added idx_user_comment (user_id, comment_id) index for viewer_reactions
    queries.
  rationale: Round 1 data reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: 'Resolved write-through vs buffer contradiction: adopted write-behind with
    speculative Redis INCRBY for immediate consistency.'
  rationale: Round 1 perf reviewer critical issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Redis keys use hash-tag-free format for natural slot distribution. Added
    per-slot monitoring and hot key escalation to dedicated instance.
  rationale: Round 1 perf reviewer critical issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Upgraded L1 from LRU 2048 to Caffeine TinyLFU 32768 entries for better
    hit rate under skewed workloads.
  rationale: Round 1 perf reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Added explicit degradation ladder (Level 0-3) covering all Redis/MySQL
    failure combinations.
  rationale: Round 1 perf reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Added P2 alert at p99>100ms/3min to catch early SLO drift before P1 threshold.
  rationale: Round 1 perf reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: 'Replaced PERMISSION_DENIED for shadow-ban with phantom write pattern:
    accept call, suppress persistence, show only in viewer''s own view.'
  rationale: Round 1 security reviewer critical issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: 'Added explicit server-side enum validation: reaction_type must be in {1..6},
    otherwise INVALID_ARGUMENT.'
  rationale: Round 1 security reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Added per-comment inbound limit (200/min) and per-IP/CIDR (/24) burst limit
    (50/min) for multi-account defense.
  rationale: Round 1 security reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Replaced static mob threshold with Z-score relative spike detection on
    SAD+ANGRY combined with cold-start baseline.
  rationale: Round 1 security reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_pitfall
  scope: roundtable/round_1
  summary: 'Accepted risk: TOCTOU gap accepted: phantom write eliminates security-sensitive
    case; remaining gap handled by eventual reconciliation.'
  rationale: Round 1 security reviewer identified, architect accepted with stated
    reason
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: 'Added content-safety service failure to failure table: fail-closed with
    circuit breaker, returns UNAVAILABLE.'
  rationale: Round 1 qa reviewer critical issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: 'Replaced DROP TABLE rollback with soft rollback: RENAME TABLE to archived,
    preserve data 90 days.'
  rationale: Round 1 qa reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Added testability section with contract tests, integration tests, and scenario
    test matrix.
  rationale: Round 1 qa reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_1
  summary: Added quantitative canary gates table with per-stage metrics thresholds
    and automatic rollback conditions.
  rationale: Round 1 qa reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_2
  summary: UK removed is_active, now UK(comment_id, user_id, reaction_type) only.
    INSERT ON DUPLICATE KEY UPDATE for toggle.
  rationale: Round 2 data reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_2
  summary: Added compensating HINCRBY -1 on DB write failure to prevent Redis count
    drift.
  rationale: Round 2 data reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_2
  summary: Split P1 alert into read-path (p99>150ms) and write-path (p99>350ms) to
    accommodate 200ms safety check.
  rationale: Round 2 perf reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_2
  summary: Explicitly specified fail-closed for safety check timeout. Async path is
    for deep analysis only.
  rationale: Round 2 security reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786
- type: new_adr
  scope: roundtable/round_2
  summary: 'Added complete chaos engineering runbook (§8): 7 fault scenarios, injection
    methods, pass/fail criteria, exercise cadence.'
  rationale: Round 2 qa reviewer major issue -> architect fixed
  source: xteam-session/2700e9a4-a773-476e-bc94-7d0c073fe786

```
