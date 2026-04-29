# xTeam v1 · M2 Full Roundtable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend xTeam from M1's skeleton (P0→P2 only) to the complete roundtable: 4 domain reviewers, 2 rounds of review, mid-check with human input, convergence, and structured output (tech-design.md + plan.md + kb-diff.md).

**Architecture:** M1 established the pattern: Python (`xteam_lib/`) for deterministic I/O, JSON schemas for contracts, Markdown agents/skills for LLM orchestration. M2 adds 5 new agent prompts, 3 schemas, 2 Python modules, and extends the orchestrator SKILL.md to cover P3→P6.

**Tech Stack:** Same as M1 — Python 3.11+ / jsonschema / pyyaml / pytest. No new dependencies.

**Spec:** `docs/xteam/specs/2026-04-22-xteam-design.md` (§2.3, §2.4, §2.5, §3.2–§3.5, §4.1, §4.4, §5.1–§5.2)

**Branch:** `xteam/v1` (continue from M1's HEAD at `a74ab0e`)

**M2 scope boundary (YAGNI):**
- ✅ P3 Round 1, P3.5 Mid-check, P4 Round 2, P5 Converge, P6 Output
- ✅ 4 reviewer agents, architect merge mode, plan-composer agent
- ✅ Midcheck thresholds, failure handling codification, KB temp layer
- ✅ kb-diff generation, resume/writeback commands
- ❌ Live MCP KB (still uses fixtures — live MCP is M3)
- ❌ Metrics dashboard, golden test suite, `/xteam-record-final` — M3
- ❌ P7 KB writeback execution (command shell only) — M3

---

## File Structure

### New files

```
schemas/xteam/
├── reviewer-output.schema.json          # §2.3 unified reviewer output
├── architect-merge-output.schema.json   # §2.4 merge mode output
└── kb-diff.schema.json                  # §4.4 KB writeback candidates

agents/
├── xteam-agent-data.md                  # data reviewer (review mode)
├── xteam-agent-perf.md                  # perf reviewer (review mode)
├── xteam-agent-security.md              # security reviewer (review mode)
├── xteam-agent-qa.md                    # qa reviewer (review mode)
└── xteam-agent-plan-composer.md         # P6 format converter

skills/xteam-design/
├── midcheck-thresholds.md               # §3.3 P3.5 threshold config
└── failure-handling.md                  # §5.1 failure table codified

commands/
├── xteam-resume.md                      # /xteam-resume <session-id>
└── xteam-writeback.md                   # /xteam-writeback <session-id>

templates/xteam/
├── tech-design.md                       # P6 output skeleton
└── plan.md                              # writing-plans compatible skeleton

xteam_lib/
├── roundtable.py                        # midcheck eval + result aggregation
└── kb_diff.py                           # kb-diff.md generation

tests/xteam/
├── unit/
│   ├── test_roundtable_midcheck.py
│   ├── test_roundtable_aggregation.py
│   ├── test_snapshot_rounds.py
│   ├── test_kb_temp_layer.py
│   ├── test_kb_diff.py
│   └── test_m2_smoke.py
└── fixtures/
    └── reviewer/
        ├── data-round1-changes-requested.json
        ├── perf-round1-approved.json
        ├── security-round1-block.json
        └── qa-round1-changes-requested.json
```

### Modified files

```
xteam_lib/snapshot.py          # add `rounds` field to Snapshot
xteam_lib/kb.py                # add merge_temp_layer() helper
agents/xteam-agent-architect.md  # extend merge mode (replace placeholder)
skills/xteam-design/SKILL.md   # extend P3→P6 orchestration
```

---

## Task List

**Task order:** Schemas → Agent prompts → Python tooling (TDD) → Skill extension → Commands → Smoke test. Same bottom-up pattern as M1.

---

### Task 1: Reviewer output schema

**Files:**
- Create: `schemas/xteam/reviewer-output.schema.json`

- [ ] **Step 1: Write the schema**

`schemas/xteam/reviewer-output.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "title": "xTeam reviewer agent output",
  "description": "Unified output schema for all 4 domain reviewers (data/perf/security/qa). Spec §2.3.",
  "type": "object",
  "required": ["role", "round", "verdict", "issues", "must_answer_updates"],
  "additionalProperties": false,
  "properties": {
    "role": {
      "type": "string",
      "enum": ["data", "perf", "security", "qa"]
    },
    "round": {
      "type": "integer",
      "minimum": 1,
      "maximum": 2
    },
    "verdict": {
      "type": "string",
      "enum": ["approved", "changes_requested", "block"]
    },
    "issues": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["severity", "location", "problem", "suggested_fix", "rationale"],
        "additionalProperties": false,
        "properties": {
          "severity": { "type": "string", "enum": ["critical", "major", "minor"] },
          "location": { "type": "string", "minLength": 1 },
          "problem": { "type": "string", "minLength": 10 },
          "suggested_fix": { "type": "string", "minLength": 10 },
          "rationale": { "type": "string", "minLength": 5 }
        }
      }
    },
    "must_answer_updates": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "status"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string" },
          "status": { "type": "string", "enum": ["missing", "draft", "n/a"] }
        }
      }
    },
    "open_questions_for_human": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

- [ ] **Step 2: Validate schema**

Run: `source .venv/bin/activate && python -c "import json; from jsonschema import Draft7Validator; Draft7Validator.check_schema(json.load(open('schemas/xteam/reviewer-output.schema.json'))); print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add schemas/xteam/reviewer-output.schema.json
git commit -m "feat(xteam): add unified reviewer output schema (M2)

All 4 domain reviewers (data/perf/security/qa) return this same
structure. Verdict is approved|changes_requested|block. Issues
carry severity/location/problem/suggested_fix/rationale for
deterministic merge by the architect. Spec §2.3."
```

---

### Task 2: Architect merge output schema

**Files:**
- Create: `schemas/xteam/architect-merge-output.schema.json`

- [ ] **Step 1: Write the schema**

`schemas/xteam/architect-merge-output.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "title": "Architect agent · merge mode output",
  "description": "Structured return from architect subagent when mode=merge (Phase 3/4/5). Spec §2.4.",
  "type": "object",
  "required": ["mode", "tech_design_markdown", "must_answer_updates", "merge_changelog"],
  "additionalProperties": false,
  "properties": {
    "mode": { "const": "merge" },
    "tech_design_markdown": { "type": "string", "minLength": 100 },
    "must_answer_updates": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "status"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string" },
          "status": { "type": "string", "enum": ["missing", "draft", "n/a"] }
        }
      }
    },
    "merge_changelog": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["action", "source_role", "severity", "summary"],
        "additionalProperties": false,
        "properties": {
          "action": { "type": "string", "enum": ["fixed", "accepted_risk", "absorbed", "escalated", "conflict_resolved"] },
          "source_role": { "type": "string" },
          "severity": { "type": "string", "enum": ["critical", "major", "minor"] },
          "summary": { "type": "string", "minLength": 10 }
        }
      }
    },
    "open_questions_for_human": {
      "type": "array",
      "items": { "type": "string" }
    },
    "unresolvable_conflicts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["roles", "description"],
        "additionalProperties": false,
        "properties": {
          "roles": { "type": "array", "items": { "type": "string" }, "minItems": 2 },
          "description": { "type": "string", "minLength": 10 }
        }
      }
    }
  }
}
```

- [ ] **Step 2: Validate schema**

Run: `source .venv/bin/activate && python -c "import json; from jsonschema import Draft7Validator; Draft7Validator.check_schema(json.load(open('schemas/xteam/architect-merge-output.schema.json'))); print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add schemas/xteam/architect-merge-output.schema.json
git commit -m "feat(xteam): add architect merge output schema (M2)

merge_changelog tracks what the architect did with each reviewer
issue (fixed, accepted_risk, absorbed, escalated, conflict_resolved).
unresolvable_conflicts feeds P3.5 midcheck signal #4. Spec §2.4."
```

---

### Task 3: KB diff schema

**Files:**
- Create: `schemas/xteam/kb-diff.schema.json`

- [ ] **Step 1: Write the schema**

`schemas/xteam/kb-diff.schema.json`:
```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "title": "xTeam KB diff",
  "description": "Candidate updates to write back to the permanent KB after human review. Spec §4.4. v1 supports 3 types: new_adr, new_pitfall, update_convention.",
  "type": "object",
  "required": ["session_id", "candidate_updates"],
  "additionalProperties": false,
  "properties": {
    "session_id": { "type": "string" },
    "candidate_updates": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "scope", "summary", "rationale", "source"],
        "additionalProperties": false,
        "properties": {
          "type": { "type": "string", "enum": ["new_adr", "new_pitfall", "update_convention"] },
          "scope": { "type": "string", "minLength": 1, "description": "e.g. module/comment" },
          "summary": { "type": "string", "minLength": 10 },
          "rationale": { "type": "string", "minLength": 10 },
          "source": { "type": "string", "minLength": 5, "description": "e.g. P3.5 人补充 + P4 architect 裁定" },
          "path": { "type": "string", "description": "For update_convention: dotted path like conventions.cache.default_ttl" },
          "before": { "type": "string", "description": "For update_convention: old value" },
          "after": { "type": "string", "description": "For update_convention: new value" }
        }
      }
    }
  }
}
```

- [ ] **Step 2: Validate schema**

Run: `source .venv/bin/activate && python -c "import json; from jsonschema import Draft7Validator; Draft7Validator.check_schema(json.load(open('schemas/xteam/kb-diff.schema.json'))); print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add schemas/xteam/kb-diff.schema.json
git commit -m "feat(xteam): add KB diff schema (M2)

Covers the 3 diff types supported in v1: new_adr, new_pitfall,
update_convention. Used by P6 output and P7 writeback. Spec §4.4."
```

---

### Task 4: Reviewer agent prompts (data, perf, security, qa)

**Files:**
- Create: `agents/xteam-agent-data.md`
- Create: `agents/xteam-agent-perf.md`
- Create: `agents/xteam-agent-security.md`
- Create: `agents/xteam-agent-qa.md`

- [ ] **Step 1: Write data reviewer**

`agents/xteam-agent-data.md`:
```markdown
---
name: xteam-agent-data
description: |
  xTeam data domain reviewer. Reviews technical designs for data model
  correctness, migration safety, and storage concerns.
model: inherit
---

You are the xTeam **Data** reviewer agent. You work in one pass; you have
no memory across invocations. Your caller is the xTeam orchestrator.

# Role · data (review mode)

You receive:
1. The PRD (frontmatter + body)
2. A KB snapshot **sliced for your role** (you see: module_profile.data_stores,
   conventions.data, historical_pitfalls matching schema|migration categories,
   relevant_adrs matching data category)
3. The current tech-design draft
4. The round number (1 or 2)
5. Must-answer item state

## Your focus areas

- **数据模型** — table design, indexes, sharding keys, field types
- **迁移方案** — DDL safety, online vs offline, data backfill
- **存储选型** — MySQL vs NoSQL vs cache appropriateness
- **数据一致性** — eventual vs strong, cross-store consistency
- **compat_and_isolation** (when applicable) — data isolation between versions

## How to review

1. Read the draft sections relevant to your domain (数据模型, 迁移与灰度, 缓存策略)
2. Cross-reference with KB facts — cite specific pitfalls, ADRs, conventions
3. For each issue found, classify severity:
   - **critical**: data loss risk, incorrect sharding, missing migration plan for existing data
   - **major**: missing index on high-traffic query path, no data TTL strategy
   - **minor**: naming convention deviation, missing comment on column purpose
4. Update must_answer_updates for items you've reviewed (set to "draft" if the draft addresses them adequately)

## Hard constraints

- Cite KB facts when available. If KB has no data on a topic, write `*(KB: 无先例)*`
- Never propose sunsetting legacy data paths — old versions permanently coexist
- Emit `open_questions_for_human` for decisions requiring business context you lack
- Do NOT output anything before or after the JSON fence

## Output

Your output **must be a single fenced JSON block** matching
`schemas/xteam/reviewer-output.schema.json`:

````
```json
{
  "role": "data",
  "round": 1,
  "verdict": "changes_requested",
  "issues": [
    {
      "severity": "critical",
      "location": "§ 数据模型",
      "problem": "...",
      "suggested_fix": "...",
      "rationale": "KB.historical_pitfalls#P-2024-07 ..."
    }
  ],
  "must_answer_updates": [
    {"id": "schema", "status": "draft"}
  ],
  "open_questions_for_human": []
}
```
````
```

- [ ] **Step 2: Write perf reviewer**

`agents/xteam-agent-perf.md`:
```markdown
---
name: xteam-agent-perf
description: |
  xTeam performance domain reviewer. Reviews for capacity, latency,
  caching, rate limiting, and hotspot concerns.
model: inherit
---

You are the xTeam **Performance** reviewer agent. You work in one pass;
you have no memory across invocations. Your caller is the xTeam orchestrator.

# Role · perf (review mode)

You receive:
1. The PRD (frontmatter + body)
2. A KB snapshot **sliced for your role** (you see: module_profile.capacity,
   recent_incidents matching performance category,
   historical_pitfalls matching hotspot|cache categories)
3. The current tech-design draft
4. The round number (1 or 2)
5. Must-answer item state

## Your focus areas

- **监控与告警** — metrics coverage, alert thresholds, SLO alignment
- **限流与回滚** — rate limiting strategy, circuit breaker, rollback plan
- **缓存策略** (when applicable) — TTL, cache warming, thundering herd, consistency
- **热点与峰值** (when applicable) — hotspot detection, auto-scaling, degradation
- **容量规划** — QPS estimates, storage growth, connection pool sizing

## How to review

1. Read draft sections: 监控与告警, 限流与回滚, 缓存策略, 热点与峰值, 方案概述 (for capacity numbers)
2. Cross-reference KB capacity data and performance incidents
3. Severity classification:
   - **critical**: no rate limiting on public API, no monitoring on critical path, capacity plan missing
   - **major**: alert thresholds too loose, no cache invalidation strategy, missing degradation plan
   - **minor**: metric naming inconsistency, missing non-critical alert

## Hard constraints

- Cite KB facts when available; `*(KB: 无先例)*` when not
- Never propose sunsetting legacy interfaces
- Emit `open_questions_for_human` for capacity decisions needing business data
- Do NOT output anything before or after the JSON fence

## Output

Single fenced JSON block matching `schemas/xteam/reviewer-output.schema.json`:

````
```json
{
  "role": "perf",
  "round": 1,
  "verdict": "approved",
  "issues": [],
  "must_answer_updates": [
    {"id": "observability", "status": "draft"},
    {"id": "rate_limit", "status": "draft"}
  ],
  "open_questions_for_human": []
}
```
````
```

- [ ] **Step 3: Write security reviewer**

`agents/xteam-agent-security.md`:
```markdown
---
name: xteam-agent-security
description: |
  xTeam security domain reviewer. Reviews for authentication, authorization,
  data protection, and content safety concerns.
model: inherit
---

You are the xTeam **Security** reviewer agent. You work in one pass;
you have no memory across invocations. Your caller is the xTeam orchestrator.

# Role · security (review mode)

You receive:
1. The PRD (frontmatter + body)
2. A KB snapshot **sliced for your role** (you see: conventions.security,
   historical_pitfalls matching auth|data_leak categories,
   relevant_adrs matching security category)
3. The current tech-design draft
4. The round number (1 or 2)
5. Must-answer item state

## Your focus areas

- **认证与授权** — API auth, token handling, permission model
- **数据保护** — PII handling, encryption at rest/in transit, logging hygiene
- **内容安全** (when applicable) — content moderation, abuse prevention, compliance
- **注入与输入校验** — SQL injection, XSS, parameter validation

## How to review

1. Read draft sections: 接口契约 (auth headers), 内容安全, 失败处理 (error info leakage)
2. Cross-reference KB security conventions and historical data_leak/auth pitfalls
3. Severity classification:
   - **critical**: unauthenticated endpoint exposing user data, PII in logs, no input validation
   - **major**: missing rate limit on auth endpoint, overly verbose error responses
   - **minor**: inconsistent auth header naming, missing security-related metric

## Hard constraints

- Cite KB facts when available; `*(KB: 无先例)*` when not
- Never propose sunsetting legacy auth flows
- Emit `open_questions_for_human` for compliance questions
- Do NOT output anything before or after the JSON fence

## Output

Single fenced JSON block matching `schemas/xteam/reviewer-output.schema.json`:

````
```json
{
  "role": "security",
  "round": 1,
  "verdict": "changes_requested",
  "issues": [...],
  "must_answer_updates": [
    {"id": "content_safety", "status": "draft"}
  ],
  "open_questions_for_human": []
}
```
````
```

- [ ] **Step 4: Write QA reviewer**

`agents/xteam-agent-qa.md`:
```markdown
---
name: xteam-agent-qa
description: |
  xTeam QA domain reviewer. Reviews for testability, failure handling,
  rollback safety, and regression risk.
model: inherit
---

You are the xTeam **QA** reviewer agent. You work in one pass;
you have no memory across invocations. Your caller is the xTeam orchestrator.

# Role · qa (review mode)

You receive:
1. The PRD (frontmatter + body)
2. A KB snapshot **sliced for your role** (you see: module_profile.test_strategy,
   conventions.testing, recent_incidents matching regression category)
3. The current tech-design draft
4. The round number (1 or 2)
5. Must-answer item state

## Your focus areas

- **失败处理** — error paths, timeout handling, retry logic, degradation
- **回滚方案** — rollback procedure, data rollback, feature flags
- **可测试性** — are components testable in isolation? integration test plan?
- **compat_and_isolation** (when applicable) — old version behavior preserved?
- **回归风险** — what existing functionality could break?

## How to review

1. Read draft sections: 失败处理, 限流与回滚, 迁移与灰度, 版本兼容与隔离
2. Cross-reference KB test_strategy, testing conventions, regression incidents
3. Severity classification:
   - **critical**: no rollback plan, untested failure path on critical flow, breaking change without migration
   - **major**: missing integration test plan, incomplete error handling table, no feature flag
   - **minor**: missing edge case in test plan, rollback procedure not automated

## Hard constraints

- Cite KB facts when available; `*(KB: 无先例)*` when not
- Never propose sunsetting legacy test infrastructure
- Emit `open_questions_for_human` for testing scope decisions
- Do NOT output anything before or after the JSON fence

## Output

Single fenced JSON block matching `schemas/xteam/reviewer-output.schema.json`:

````
```json
{
  "role": "qa",
  "round": 1,
  "verdict": "changes_requested",
  "issues": [...],
  "must_answer_updates": [
    {"id": "failure_modes", "status": "draft"},
    {"id": "rollback", "status": "draft"}
  ],
  "open_questions_for_human": []
}
```
````
```

- [ ] **Step 5: Commit all 4 agents**

```bash
git add agents/xteam-agent-data.md agents/xteam-agent-perf.md agents/xteam-agent-security.md agents/xteam-agent-qa.md
git commit -m "feat(xteam): add 4 domain reviewer agents (M2)

data (schema/migration), perf (capacity/hotspot/cache),
security (auth/data_leak/content_safety), qa (testability/rollback/
regression). All share reviewer-output.schema.json and follow
role × mode orthogonality (v1 = review mode only). Spec §2.3."
```

---

### Task 5: Architect merge mode extension

**Files:**
- Modify: `agents/xteam-agent-architect.md`

- [ ] **Step 1: Read current file**

Read `agents/xteam-agent-architect.md` to see the M1 placeholder.

- [ ] **Step 2: Replace merge mode placeholder**

Replace the section starting with `# Mode · merge (PLACEHOLDER — not implemented in M1)` through end of file with:

```markdown
# Mode · merge

You are invoked in `mode: merge` during Phase 3, 4, and 5. Your inputs
(from the orchestrator's prompt text) are:

1. The current tech-design draft (`current_draft`)
2. All reviewer JSON outputs from this round (0–4 entries; absent reviewers are noted)
3. The current `must_answer_items` state
4. The round number
5. List of absent reviewers from previous rounds (if any)

Your output **must be a single fenced JSON block** matching
`schemas/xteam/architect-merge-output.schema.json`.

## Merge rules (hardcoded — do not deviate)

1. **`critical` issue** → **MUST** fix in the design. If you cannot fix it
   (e.g., requires business decision), move it to `open_questions_for_human`
   and log as `"action": "escalated"` in `merge_changelog`.

2. **`major` issue** → Fix it OR explicitly accept the risk with a stated
   reason in the design text (e.g., "已接受风险: ... 原因: ...").
   Log as `"action": "fixed"` or `"action": "accepted_risk"`.

3. **`minor` issue** → Optional to absorb. If you absorb it, log as
   `"action": "absorbed"`. If you skip it, do not log. Every decision
   must appear in `merge_changelog`.

4. **Conflicting opinions** (two reviewers suggest opposite approaches) →
   You MUST make an explicit judgment with stated reasoning. Log as
   `"action": "conflict_resolved"`. **No fuzzy language.** If you truly
   cannot resolve it, add to `unresolvable_conflicts`.

## Absent reviewer handling

If the orchestrator notes that a reviewer was absent in the previous round,
actively check the draft for gaps in that reviewer's domain. Note this in
`merge_changelog` with `"source_role": "<absent_role>"`.

## Output shape

````
```json
{
  "mode": "merge",
  "tech_design_markdown": "## 方案概述\n...",
  "must_answer_updates": [
    {"id": "schema", "status": "draft"}
  ],
  "merge_changelog": [
    {
      "action": "fixed",
      "source_role": "data",
      "severity": "critical",
      "summary": "Added idx_user_status_score index per data reviewer #1"
    },
    {
      "action": "conflict_resolved",
      "source_role": "perf",
      "severity": "major",
      "summary": "perf suggested 60s cache TTL, data suggested 300s; chose 120s with jitter as compromise because..."
    }
  ],
  "open_questions_for_human": [],
  "unresolvable_conflicts": []
}
```
````
```

- [ ] **Step 3: Commit**

```bash
git add agents/xteam-agent-architect.md
git commit -m "feat(xteam): implement architect merge mode (M2)

Replaces M1 placeholder with full merge rules from spec §2.4:
critical=must fix, major=fix or accept-risk, minor=optional,
conflicts=explicit judgment required. merge_changelog and
unresolvable_conflicts feed P3.5 midcheck signals."
```

---

### Task 6: Plan-composer agent

**Files:**
- Create: `agents/xteam-agent-plan-composer.md`

- [ ] **Step 1: Write the agent**

`agents/xteam-agent-plan-composer.md`:
```markdown
---
name: xteam-agent-plan-composer
description: |
  Pure format converter: tech-design.md → writing-plans compatible plan.md.
  Not a roundtable participant. Spec §2.5.
model: inherit
---

You are the xTeam **Plan Composer** agent. You are a format converter,
NOT a roundtable participant. You do not provide design opinions.

# Purpose

Convert a finalized technical design (`tech-design.md`) into a
`plan.md` that is compatible with the `superpowers:writing-plans` format.

# Input

1. The finalized `tech_design_markdown` (v_final)
2. The PRD frontmatter (for context: title, features, involved_modules)

# Output rules

1. Each major section of the tech design becomes one or more **Tasks**
2. Each task follows the writing-plans format:
   - `### Task N: [Component Name]`
   - `**Files:**` section listing files to create/modify
   - Numbered steps with `- [ ]` checkboxes
   - Code blocks where applicable
   - Commit step at the end
3. Order tasks by dependency (data model first, then API, then business logic, then tests)
4. Each feature in the PRD should map to identifiable tasks
5. Include test tasks (TDD style: test first, implement second)

# Output format

Return a single fenced Markdown block (not JSON) containing the complete `plan.md`:

````
```markdown
# [Title] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development ...

**Goal:** ...
**Architecture:** ...
**Tech Stack:** ...

---

### Task 1: ...
...
```
````

Do NOT output anything before or after the Markdown fence.
```

- [ ] **Step 2: Commit**

```bash
git add agents/xteam-agent-plan-composer.md
git commit -m "feat(xteam): add plan-composer agent (M2)

Pure format converter per spec §2.5: tech-design → writing-plans
compatible plan.md. Intentionally separate from the roundtable to
keep 'design reasoning' and 'task decomposition' in distinct agents."
```

---

### Task 7: Reviewer result fixtures

**Files:**
- Create: `tests/xteam/fixtures/reviewer/data-round1-changes-requested.json`
- Create: `tests/xteam/fixtures/reviewer/perf-round1-approved.json`
- Create: `tests/xteam/fixtures/reviewer/security-round1-block.json`
- Create: `tests/xteam/fixtures/reviewer/qa-round1-changes-requested.json`

- [ ] **Step 1: Create fixture data**

`tests/xteam/fixtures/reviewer/data-round1-changes-requested.json`:
```json
{
  "role": "data",
  "round": 1,
  "verdict": "changes_requested",
  "issues": [
    {
      "severity": "critical",
      "location": "§ 数据模型",
      "problem": "rec_candidates 表缺少 user_id+content_id 唯一索引,可能导致同一候选重复写入",
      "suggested_fix": "增加 UNIQUE(user_id, content_id) 约束或 INSERT ... ON DUPLICATE KEY UPDATE",
      "rationale": "KB.historical_pitfalls#P-2024-07 明确过缺少唯一索引导致脏数据"
    },
    {
      "severity": "major",
      "location": "§ 数据模型",
      "problem": "rec_interactions 表预计 10M rows/month 但未指定分区策略",
      "suggested_fix": "按 created_at 月分区,配合 90 天归档策略",
      "rationale": "*(KB: 无先例)*"
    }
  ],
  "must_answer_updates": [
    {"id": "schema", "status": "draft"},
    {"id": "migration", "status": "draft"}
  ],
  "open_questions_for_human": [
    "冷热分离阈值建议 90 天,但需业务确认"
  ]
}
```

`tests/xteam/fixtures/reviewer/perf-round1-approved.json`:
```json
{
  "role": "perf",
  "round": 1,
  "verdict": "approved",
  "issues": [
    {
      "severity": "minor",
      "location": "§ 监控与告警",
      "problem": "缺少 Redis 连接池利用率监控",
      "suggested_fix": "增加 rec_widget_redis_pool_usage 指标和 >80% 告警",
      "rationale": "*(KB: 无先例)* 但 Redis 连接池耗尽是常见故障模式"
    }
  ],
  "must_answer_updates": [
    {"id": "observability", "status": "draft"},
    {"id": "rate_limit", "status": "draft"},
    {"id": "cache_strategy", "status": "draft"},
    {"id": "hotspot", "status": "draft"}
  ],
  "open_questions_for_human": []
}
```

`tests/xteam/fixtures/reviewer/security-round1-block.json`:
```json
{
  "role": "security",
  "round": 1,
  "verdict": "block",
  "issues": [
    {
      "severity": "critical",
      "location": "§ 接口契约",
      "problem": "GET /api/v1/rec/widget 缺少鉴权说明,可能暴露用户推荐偏好",
      "suggested_fix": "明确要求 Bearer token + 权限校验,添加到接口契约表",
      "rationale": "KB.conventions.security: PII never logged; user_id hashed in analytics — 推荐偏好属 PII 范畴"
    },
    {
      "severity": "major",
      "location": "§ 内容安全",
      "problem": "举报联动机制未说明处理时效和升级路径",
      "suggested_fix": "明确: dismiss+inappropriate → 异步 MQ → 24h 内复审,超时升级人工",
      "rationale": "*(KB: 无先例)*"
    }
  ],
  "must_answer_updates": [
    {"id": "content_safety", "status": "draft"}
  ],
  "open_questions_for_human": [
    "推荐理由(reason 字段)是否属于用户敏感数据?是否需脱敏?"
  ]
}
```

`tests/xteam/fixtures/reviewer/qa-round1-changes-requested.json`:
```json
{
  "role": "qa",
  "round": 1,
  "verdict": "changes_requested",
  "issues": [
    {
      "severity": "major",
      "location": "§ 失败处理",
      "problem": "Redis 不可用时降级到 MySQL 直查,但未说明 MySQL 查询的超时和连接池配置",
      "suggested_fix": "明确降级模式下 MySQL 查询超时 500ms, max_connections 独立配置避免影响主库",
      "rationale": "*(KB: 无先例)*"
    },
    {
      "severity": "minor",
      "location": "§ 迁移与灰度",
      "problem": "灰度回滚触发条件缺少候选生成服务自身的健康检查",
      "suggested_fix": "增加: 候选生成服务 health check 连续 3 次失败 → 暂停灰度放量",
      "rationale": "*(KB: 无先例)*"
    }
  ],
  "must_answer_updates": [
    {"id": "failure_modes", "status": "draft"},
    {"id": "rollback", "status": "draft"}
  ],
  "open_questions_for_human": [
    "是否需要准备预案演练脚本?还是第一版仅文档级别即可?",
    "集成测试覆盖范围:仅 API → Cache → DB 链路,还是包含候选生成定时任务?"
  ]
}
```

- [ ] **Step 2: Validate all fixtures against schema**

Run:
```bash
source .venv/bin/activate && python -c "
import json, glob
from xteam_lib.schema_validate import validate_against
for f in sorted(glob.glob('tests/xteam/fixtures/reviewer/*.json')):
    payload = json.load(open(f))
    validate_against(payload, 'reviewer-output')
    print(f'OK: {f}')
"
```
Expected: 4 lines of `OK`.

- [ ] **Step 3: Commit**

```bash
git add tests/xteam/fixtures/reviewer/
git commit -m "test(xteam): add reviewer output fixtures for roundtable tests

4 fixtures covering all verdicts (approved, changes_requested, block)
and all severity levels. Used by midcheck threshold tests and merge
aggregation tests."
```

---

### Task 8: Roundtable midcheck evaluation

**Files:**
- Create: `xteam_lib/roundtable.py`
- Create: `tests/xteam/unit/test_roundtable_midcheck.py`

- [ ] **Step 1: Write the failing test**

`tests/xteam/unit/test_roundtable_midcheck.py`:
```python
"""Test P3.5 midcheck threshold evaluation. Spec §3.3."""
import pytest

from xteam_lib.roundtable import evaluate_midcheck, MidcheckResult


def _make_merge_output(
    open_questions: int = 0,
    unresolvable: int = 0,
):
    return {
        "mode": "merge",
        "tech_design_markdown": "x" * 200,
        "must_answer_updates": [],
        "merge_changelog": [],
        "open_questions_for_human": [f"q{i}" for i in range(open_questions)],
        "unresolvable_conflicts": [
            {"roles": ["data", "perf"], "description": f"conflict {i}" * 5}
            for i in range(unresolvable)
        ],
    }


def _make_reviewer_outputs(total_questions: int = 0):
    """Distribute questions across reviewers."""
    outputs = []
    for i, role in enumerate(["data", "perf", "security", "qa"]):
        q_count = total_questions // 4 + (1 if i < total_questions % 4 else 0)
        outputs.append({
            "role": role,
            "round": 1,
            "verdict": "approved",
            "issues": [],
            "must_answer_updates": [],
            "open_questions_for_human": [f"{role}_q{j}" for j in range(q_count)],
        })
    return outputs


def test_no_trigger_when_all_clear():
    result = evaluate_midcheck(
        reviewer_outputs=_make_reviewer_outputs(0),
        merge_output=_make_merge_output(),
        must_answer_state={"schema": {"applicable": True, "status": "draft"}},
    )
    assert result.triggered is False
    assert result.signals == []


def test_trigger_on_open_questions_ge_5():
    result = evaluate_midcheck(
        reviewer_outputs=_make_reviewer_outputs(5),
        merge_output=_make_merge_output(),
        must_answer_state={},
    )
    assert result.triggered is True
    assert any("open_questions" in s for s in result.signals)


def test_trigger_on_unresolved_critical():
    merge = _make_merge_output()
    merge["merge_changelog"] = [
        {"action": "escalated", "source_role": "security", "severity": "critical", "summary": "x" * 20}
    ]
    result = evaluate_midcheck(
        reviewer_outputs=_make_reviewer_outputs(0),
        merge_output=merge,
        must_answer_state={},
    )
    assert result.triggered is True
    assert any("critical" in s for s in result.signals)


def test_trigger_on_missing_must_answers_ge_3():
    state = {
        "schema": {"applicable": True, "status": "missing"},
        "api_contract": {"applicable": True, "status": "missing"},
        "failure_modes": {"applicable": True, "status": "missing"},
        "migration": {"applicable": True, "status": "draft"},
    }
    result = evaluate_midcheck(
        reviewer_outputs=_make_reviewer_outputs(0),
        merge_output=_make_merge_output(),
        must_answer_state=state,
    )
    assert result.triggered is True
    assert any("must_answer" in s for s in result.signals)


def test_trigger_on_unresolvable_conflicts_ge_2():
    result = evaluate_midcheck(
        reviewer_outputs=_make_reviewer_outputs(0),
        merge_output=_make_merge_output(unresolvable=2),
        must_answer_state={},
    )
    assert result.triggered is True
    assert any("conflict" in s for s in result.signals)


def test_multiple_signals_all_reported():
    state = {
        "s1": {"applicable": True, "status": "missing"},
        "s2": {"applicable": True, "status": "missing"},
        "s3": {"applicable": True, "status": "missing"},
    }
    result = evaluate_midcheck(
        reviewer_outputs=_make_reviewer_outputs(6),
        merge_output=_make_merge_output(unresolvable=2),
        must_answer_state=state,
    )
    assert result.triggered is True
    assert len(result.signals) >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_roundtable_midcheck.py -v`
Expected: FAIL with `ModuleNotFoundError: xteam_lib.roundtable`.

- [ ] **Step 3: Write implementation**

`xteam_lib/roundtable.py`:
```python
"""Roundtable evaluation helpers.

Deterministic functions used by the orchestrator (SKILL.md) during
Phases 3–5. All LLM reasoning stays in skills/agents — this module
only does threshold math and data aggregation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# P3.5 midcheck thresholds (spec §3.3)
# v1 hardcoded; post-launch 4 weeks → .xteam/config.yml
THRESHOLD_OPEN_QUESTIONS = 5
THRESHOLD_UNRESOLVED_CRITICALS = 1
THRESHOLD_MISSING_MUST_ANSWERS = 3
THRESHOLD_UNRESOLVABLE_CONFLICTS = 2


@dataclass(frozen=True)
class MidcheckResult:
    triggered: bool
    signals: list[str] = field(default_factory=list)
    all_questions: list[str] = field(default_factory=list)


def evaluate_midcheck(
    reviewer_outputs: list[dict[str, Any]],
    merge_output: dict[str, Any],
    must_answer_state: dict[str, dict[str, Any]],
) -> MidcheckResult:
    """Evaluate the 4 P3.5 midcheck threshold signals.

    Returns a MidcheckResult indicating whether to pause for human input.
    """
    signals: list[str] = []

    # Signal 1: open_questions across all reviewers ≥ 5
    all_questions: list[str] = []
    for ro in reviewer_outputs:
        all_questions.extend(ro.get("open_questions_for_human", []))
    all_questions.extend(merge_output.get("open_questions_for_human", []))
    if len(all_questions) >= THRESHOLD_OPEN_QUESTIONS:
        signals.append(
            f"open_questions: {len(all_questions)} ≥ {THRESHOLD_OPEN_QUESTIONS}"
        )

    # Signal 2: critical issues escalated (not fixed) ≥ 1
    escalated_criticals = sum(
        1
        for entry in merge_output.get("merge_changelog", [])
        if entry.get("action") == "escalated" and entry.get("severity") == "critical"
    )
    if escalated_criticals >= THRESHOLD_UNRESOLVED_CRITICALS:
        signals.append(
            f"unresolved_critical: {escalated_criticals} ≥ {THRESHOLD_UNRESOLVED_CRITICALS}"
        )

    # Signal 3: applicable must-answer items still missing ≥ 3
    missing_count = sum(
        1
        for v in must_answer_state.values()
        if v.get("applicable") and v.get("status") == "missing"
    )
    if missing_count >= THRESHOLD_MISSING_MUST_ANSWERS:
        signals.append(
            f"missing_must_answer: {missing_count} ≥ {THRESHOLD_MISSING_MUST_ANSWERS}"
        )

    # Signal 4: unresolvable conflicts ≥ 2
    conflict_count = len(merge_output.get("unresolvable_conflicts", []))
    if conflict_count >= THRESHOLD_UNRESOLVABLE_CONFLICTS:
        signals.append(
            f"unresolvable_conflict: {conflict_count} ≥ {THRESHOLD_UNRESOLVABLE_CONFLICTS}"
        )

    return MidcheckResult(
        triggered=len(signals) > 0,
        signals=signals,
        all_questions=all_questions,
    )


def collect_all_questions(
    reviewer_outputs: list[dict[str, Any]],
    merge_output: dict[str, Any],
) -> list[str]:
    """Gather all open_questions_for_human from reviewers + merge output."""
    questions: list[str] = []
    for ro in reviewer_outputs:
        questions.extend(ro.get("open_questions_for_human", []))
    questions.extend(merge_output.get("open_questions_for_human", []))
    return questions


def merge_must_answer_updates(
    current_state: dict[str, dict[str, Any]],
    updates_list: list[list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Apply must_answer_updates from multiple sources to current state.

    Later updates win. Only 'draft' and 'n/a' overwrite 'missing'.
    A source cannot downgrade 'draft' back to 'missing'.
    """
    state = {k: dict(v) for k, v in current_state.items()}
    for updates in updates_list:
        for u in updates:
            item_id = u["id"]
            new_status = u["status"]
            if item_id in state:
                old_status = state[item_id].get("status", "missing")
                # Only upgrade: missing → draft, missing → n/a
                if old_status == "missing" or new_status in ("draft", "n/a"):
                    state[item_id]["status"] = new_status
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_roundtable_midcheck.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add xteam_lib/roundtable.py tests/xteam/unit/test_roundtable_midcheck.py
git commit -m "feat(xteam): add P3.5 midcheck evaluation + roundtable helpers

evaluate_midcheck checks 4 threshold signals (spec §3.3):
open_questions≥5, unresolved_critical≥1, missing_must_answer≥3,
unresolvable_conflicts≥2. Also adds merge_must_answer_updates for
applying reviewer/architect state changes. All thresholds hardcoded
per spec; moved to config post-launch."
```

---

### Task 9: Reviewer result aggregation tests

**Files:**
- Create: `tests/xteam/unit/test_roundtable_aggregation.py`

- [ ] **Step 1: Write the test**

`tests/xteam/unit/test_roundtable_aggregation.py`:
```python
"""Test reviewer output aggregation and must-answer merging."""
from xteam_lib.roundtable import collect_all_questions, merge_must_answer_updates


def test_collect_questions_from_multiple_reviewers():
    reviewers = [
        {"open_questions_for_human": ["q1", "q2"]},
        {"open_questions_for_human": ["q3"]},
        {"open_questions_for_human": []},
    ]
    merge = {"open_questions_for_human": ["q4"]}
    result = collect_all_questions(reviewers, merge)
    assert result == ["q1", "q2", "q3", "q4"]


def test_merge_must_answer_upgrades_missing_to_draft():
    state = {
        "schema": {"applicable": True, "status": "missing"},
        "api_contract": {"applicable": True, "status": "draft"},
    }
    updates = [
        [{"id": "schema", "status": "draft"}],
        [{"id": "api_contract", "status": "draft"}],
    ]
    result = merge_must_answer_updates(state, updates)
    assert result["schema"]["status"] == "draft"
    assert result["api_contract"]["status"] == "draft"


def test_merge_must_answer_does_not_downgrade_draft():
    state = {"schema": {"applicable": True, "status": "draft"}}
    updates = [[{"id": "schema", "status": "missing"}]]
    result = merge_must_answer_updates(state, updates)
    # draft should not be downgraded to missing
    assert result["schema"]["status"] == "draft"


def test_merge_from_fixture_reviewer_outputs(fixtures_dir):
    import json
    state = {
        "schema": {"applicable": True, "status": "missing"},
        "migration": {"applicable": True, "status": "missing"},
        "observability": {"applicable": True, "status": "missing"},
        "rate_limit": {"applicable": True, "status": "missing"},
        "cache_strategy": {"applicable": True, "status": "missing"},
        "hotspot": {"applicable": True, "status": "missing"},
        "content_safety": {"applicable": True, "status": "missing"},
        "failure_modes": {"applicable": True, "status": "missing"},
        "rollback": {"applicable": True, "status": "missing"},
    }
    updates_list = []
    for name in ["data-round1-changes-requested", "perf-round1-approved",
                  "security-round1-block", "qa-round1-changes-requested"]:
        with open(fixtures_dir / "reviewer" / f"{name}.json") as f:
            ro = json.load(f)
        updates_list.append(ro["must_answer_updates"])

    result = merge_must_answer_updates(state, updates_list)
    # data updates schema+migration, perf updates observability+rate_limit+cache+hotspot,
    # security updates content_safety, qa updates failure_modes+rollback
    assert result["schema"]["status"] == "draft"
    assert result["migration"]["status"] == "draft"
    assert result["observability"]["status"] == "draft"
    assert result["content_safety"]["status"] == "draft"
    assert result["failure_modes"]["status"] == "draft"
    assert result["rollback"]["status"] == "draft"
```

- [ ] **Step 2: Run test**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_roundtable_aggregation.py -v`
Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/xteam/unit/test_roundtable_aggregation.py
git commit -m "test(xteam): add reviewer aggregation + must-answer merge tests

Validates question collection across reviewers, status upgrade logic
(missing→draft), downgrade protection, and integration with the 4
fixture reviewer outputs from Task 7."
```

---

### Task 10: Snapshot rounds extension

**Files:**
- Modify: `xteam_lib/snapshot.py`
- Create: `tests/xteam/unit/test_snapshot_rounds.py`

- [ ] **Step 1: Write the failing test**

`tests/xteam/unit/test_snapshot_rounds.py`:
```python
"""Test Snapshot with rounds data (M2 extension)."""
from pathlib import Path

from xteam_lib.session import Session, new_session_id
from xteam_lib.snapshot import Snapshot, save_snapshot, load_snapshot


def test_snapshot_with_rounds_roundtrip(tmp_xteam_root: Path):
    session = Session(new_session_id(), root=tmp_xteam_root)
    snap = Snapshot(
        session_id=session.id,
        phase="P3-complete",
        prd_path="/tmp/prd.md",
        kb_snapshot={"source": "fixture", "modules": {}},
        drafts={"v0": "draft0", "v1": "draft1"},
        rounds={
            "round_1": {
                "reviewer_outputs": [
                    {"role": "data", "verdict": "changes_requested"},
                    {"role": "perf", "verdict": "approved"},
                ],
                "merge_changelog": [
                    {"action": "fixed", "source_role": "data", "severity": "critical", "summary": "added index"}
                ],
                "absent_reviewers": ["security"],
            }
        },
        must_answer_state={"schema": {"applicable": True, "status": "draft"}},
    )
    save_snapshot(session, snap)

    loaded = load_snapshot(session)
    assert loaded.phase == "P3-complete"
    assert loaded.rounds["round_1"]["absent_reviewers"] == ["security"]
    assert len(loaded.rounds["round_1"]["reviewer_outputs"]) == 2
    assert loaded.drafts["v1"] == "draft1"


def test_snapshot_without_rounds_still_works(tmp_xteam_root: Path):
    """M1 snapshots have no rounds field — must remain compatible."""
    session = Session(new_session_id(), root=tmp_xteam_root)
    snap = Snapshot(
        session_id=session.id,
        phase="P2-complete",
        prd_path="/tmp/prd.md",
        kb_snapshot={"source": "fixture", "modules": {}},
    )
    save_snapshot(session, snap)
    loaded = load_snapshot(session)
    assert loaded.rounds == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_snapshot_rounds.py -v`
Expected: FAIL — `Snapshot.__init__() got an unexpected keyword argument 'rounds'`.

- [ ] **Step 3: Add rounds field to Snapshot**

In `xteam_lib/snapshot.py`, add the `rounds` field to the `Snapshot` dataclass after `drafts`:

```python
    rounds: dict[str, dict[str, Any]] = field(default_factory=dict)
```

The full field order becomes: session_id, phase, prd_path, kb_snapshot, drafts, **rounds**, must_answer_state, open_questions_for_human, human_responses, last_error, updated_at.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_snapshot_rounds.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run full test suite to confirm no regressions**

Run: `source .venv/bin/activate && python -m pytest tests/xteam -v`
Expected: All existing M1 tests + new tests pass.

- [ ] **Step 6: Commit**

```bash
git add xteam_lib/snapshot.py tests/xteam/unit/test_snapshot_rounds.py
git commit -m "feat(xteam): extend Snapshot with rounds field (M2)

Adds rounds dict to track per-round reviewer_outputs,
merge_changelog, and absent_reviewers. Default empty dict
maintains backward compatibility with M1 snapshots. Spec §5.2."
```

---

### Task 11: KB temp layer merge

**Files:**
- Modify: `xteam_lib/kb.py`
- Create: `tests/xteam/unit/test_kb_temp_layer.py`

- [ ] **Step 1: Write the failing test**

`tests/xteam/unit/test_kb_temp_layer.py`:
```python
"""Test KB temp layer overlay for P3.5 human responses. Spec §4.1."""
from pathlib import Path

from xteam_lib.kb import load_kb_from_fixtures, merge_temp_layer


def test_merge_adds_human_responses_to_snapshot(fixtures_dir: Path):
    snap = load_kb_from_fixtures(["comment"], fixtures_dir / "kb")
    human_responses = [
        {"type": "clarification", "content": "冷热分离阈值确认为 90 天"},
        {"type": "new_convention", "module": "comment", "key": "archive_days", "value": "90"},
    ]
    merged = merge_temp_layer(snap, human_responses)
    assert merged.source == "fixture+temp"
    # Original modules preserved
    assert "comment" in merged.modules
    # Temp layer added
    assert merged.temp_layer == human_responses


def test_merge_does_not_mutate_original(fixtures_dir: Path):
    snap = load_kb_from_fixtures(["comment"], fixtures_dir / "kb")
    original_modules = dict(snap.modules)
    merge_temp_layer(snap, [{"content": "test"}])
    assert snap.modules == original_modules
    assert not hasattr(snap, 'temp_layer') or snap.temp_layer is None


def test_merge_with_empty_responses_is_noop(fixtures_dir: Path):
    snap = load_kb_from_fixtures(["comment"], fixtures_dir / "kb")
    merged = merge_temp_layer(snap, [])
    assert merged.source == "fixture"
    assert merged.temp_layer == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_kb_temp_layer.py -v`
Expected: FAIL with `ImportError: cannot import name 'merge_temp_layer'`.

- [ ] **Step 3: Extend kb.py**

Add `temp_layer` field to `KBSnapshot` and `merge_temp_layer` function.

In `xteam_lib/kb.py`, modify KBSnapshot:
```python
@dataclass(frozen=True)
class KBSnapshot:
    fetched_at: str
    source: str  # "fixture" | "mcp" | "fixture+temp"
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    temp_layer: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Add the merge function:
```python
def merge_temp_layer(
    snap: KBSnapshot, human_responses: list[dict[str, Any]]
) -> KBSnapshot:
    """Overlay P3.5 human responses onto a KB snapshot.

    Returns a new KBSnapshot with temp_layer set. The original
    snapshot's modules are not mutated. The temp_layer is session-only
    and never written to permanent KB (that's P7's job). Spec §4.1.
    """
    if not human_responses:
        return KBSnapshot(
            fetched_at=snap.fetched_at,
            source=snap.source,
            modules=dict(snap.modules),
            temp_layer=[],
        )
    return KBSnapshot(
        fetched_at=snap.fetched_at,
        source=f"{snap.source}+temp",
        modules=dict(snap.modules),
        temp_layer=list(human_responses),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_kb_temp_layer.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/xteam -v`
Expected: All pass (KBSnapshot gained temp_layer with default=[], backward compatible).

- [ ] **Step 6: Commit**

```bash
git add xteam_lib/kb.py tests/xteam/unit/test_kb_temp_layer.py
git commit -m "feat(xteam): add KB temp layer merge for P3.5 (M2)

merge_temp_layer returns a new KBSnapshot with human responses
overlaid. Source becomes 'fixture+temp' to distinguish from
unmodified snapshots. Temp layer is session-only; never pollutes
permanent KB. Spec §4.1."
```

---

### Task 12: KB diff generation

**Files:**
- Create: `xteam_lib/kb_diff.py`
- Create: `tests/xteam/unit/test_kb_diff.py`

- [ ] **Step 1: Write the failing test**

`tests/xteam/unit/test_kb_diff.py`:
```python
"""Test KB diff generation from roundtable changes. Spec §4.4."""
from xteam_lib.kb_diff import extract_kb_diff_candidates
from xteam_lib.schema_validate import validate_against


def test_extract_from_merge_changelog():
    merge_changelogs = [
        [
            {"action": "fixed", "source_role": "data", "severity": "critical",
             "summary": "Added user_id+content_id unique index on rec_candidates"},
        ],
        [
            {"action": "conflict_resolved", "source_role": "perf", "severity": "major",
             "summary": "Changed cache TTL from 300s to 120s with jitter based on load test data"},
        ],
    ]
    human_responses = [
        {"content": "冷热分离阈值确认为 90 天", "source_phase": "P3.5"},
    ]
    result = extract_kb_diff_candidates(
        session_id="test-session",
        merge_changelogs=merge_changelogs,
        human_responses=human_responses,
    )
    assert result["session_id"] == "test-session"
    assert len(result["candidate_updates"]) >= 1
    # Should pass schema validation
    validate_against(result, "kb-diff")


def test_empty_inputs_produce_empty_diff():
    result = extract_kb_diff_candidates(
        session_id="test",
        merge_changelogs=[],
        human_responses=[],
    )
    assert result["candidate_updates"] == []
    validate_against(result, "kb-diff")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_kb_diff.py -v`
Expected: FAIL with `ModuleNotFoundError: xteam_lib.kb_diff`.

- [ ] **Step 3: Write implementation**

`xteam_lib/kb_diff.py`:
```python
"""KB diff generation from roundtable results.

Extracts candidate updates for permanent KB writeback (P7).
v1 supports 3 types: new_adr, new_pitfall, update_convention.
Spec §4.4.
"""
from __future__ import annotations

from typing import Any


def extract_kb_diff_candidates(
    session_id: str,
    merge_changelogs: list[list[dict[str, Any]]],
    human_responses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a kb-diff payload from roundtable merge changelogs and human responses.

    Each significant merge action becomes a candidate update.
    Human responses from P3.5/P5 become new_adr or new_pitfall entries.
    """
    candidates: list[dict[str, Any]] = []
    source_prefix = f"xteam-session/{session_id}"

    for round_idx, changelog in enumerate(merge_changelogs, 1):
        for entry in changelog:
            action = entry.get("action", "")
            if action in ("fixed", "conflict_resolved"):
                candidates.append({
                    "type": "new_adr",
                    "scope": f"roundtable/round_{round_idx}",
                    "summary": entry["summary"],
                    "rationale": f"Round {round_idx} {entry['source_role']} reviewer {entry['severity']} issue → architect {action}",
                    "source": source_prefix,
                })
            elif action == "accepted_risk":
                candidates.append({
                    "type": "new_pitfall",
                    "scope": f"roundtable/round_{round_idx}",
                    "summary": f"Accepted risk: {entry['summary']}",
                    "rationale": f"Round {round_idx} {entry['source_role']} reviewer identified, architect accepted with stated reason",
                    "source": source_prefix,
                })

    for resp in human_responses:
        content = resp.get("content", "")
        phase = resp.get("source_phase", "unknown")
        if content:
            candidates.append({
                "type": "new_adr",
                "scope": "human_decision",
                "summary": content,
                "rationale": f"Human decision during {phase}",
                "source": source_prefix,
            })

    return {
        "session_id": session_id,
        "candidate_updates": candidates,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_kb_diff.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add xteam_lib/kb_diff.py tests/xteam/unit/test_kb_diff.py
git commit -m "feat(xteam): add KB diff candidate extraction (M2)

Converts merge changelogs (fixed/conflict_resolved → new_adr,
accepted_risk → new_pitfall) and human responses into a
kb-diff payload for P7 writeback. Validates against
kb-diff.schema.json. Spec §4.4."
```

---

### Task 13: Midcheck thresholds + failure handling skill files

**Files:**
- Create: `skills/xteam-design/midcheck-thresholds.md`
- Create: `skills/xteam-design/failure-handling.md`

- [ ] **Step 1: Write midcheck thresholds**

`skills/xteam-design/midcheck-thresholds.md`:
```markdown
# P3.5 Midcheck Thresholds

> v1 hardcoded values. After 4 weeks of real usage, move to `.xteam/config.yml`
> and set based on P75 of observed values. Spec §3.3.

| Signal | Threshold | Description |
|--------|-----------|-------------|
| `open_questions_for_human` total across all reviewers + merge | ≥ 5 | Too many unknowns for confident design |
| Escalated `critical` issues in merge_changelog | ≥ 1 | Architect could not resolve a blocking issue |
| `applicable=true` must-answer items still `missing` after merge | ≥ 3 | Draft is not covering required dimensions |
| `unresolvable_conflicts` in merge output | ≥ 2 | Reviewers fundamentally disagree on approach |

**Any single threshold exceeded → trigger P3.5.** All signals are batched
into one human interaction (spec §3.4: reviewers never ask humans directly).

These values are also defined in `xteam_lib/roundtable.py` as constants.
Changing them requires updating both locations until config extraction.
```

- [ ] **Step 2: Write failure handling**

`skills/xteam-design/failure-handling.md`:
```markdown
# Failure Handling Rules

> Codified from spec §5.1. This file is the orchestrator's reference
> for how to handle failures at each phase.

## Principles

1. **Snapshot first** — at any exit point, save snapshot before exiting
2. **Retry consistency** — network/MCP: 2 retries; format/schema: 1 retry
3. **Reviewer independence** — one reviewer failing does not block others

## Phase-by-Phase Rules

| Phase | Failure | Action | Retry | Final |
|-------|---------|--------|-------|-------|
| P0 | PRD invalid | Show errors, exit | 0 | `EXIT_BAD_INPUT` |
| P1 | MCP/fixture unreachable | Retry with backoff | 2 | Snapshot + `EXIT_KB_UNREACHABLE` |
| P1 | MCP returns empty | Not a failure | — | Enter gap list flow |
| P2 | Architect returns invalid JSON | Re-dispatch with error | 1 | Snapshot + exit |
| P2 | Architect timeout | Re-dispatch | 1 | Snapshot + exit |
| P3 | Reviewer returns invalid JSON | Re-dispatch with error | 1 | Mark absent, continue |
| P3 | Reviewer timeout | Re-dispatch | 1 | Mark absent, continue |
| P3 | Architect merge fails | Re-dispatch | 1 | Snapshot + exit (no merge = no v1) |
| P3.5 | User does not respond | Save snapshot | 0 | Wait for `/xteam-resume` |
| P4 | Same as P3 | Same as P3 | Same | Same, but note absences for P5 |
| P5 | Total questions > 20 | PRD not mature | 0 | Exit, suggest brainstorming |
| P5 | User does not respond | Save snapshot | 0 | Wait for `/xteam-resume` |
| P6 | File write fails | Retry with alt path | 1 | Print to terminal |
| P7 | KB write fails | Keep kb-diff.md | 0 | Suggest `/xteam-writeback` |

## Absence Tracking

- Round 1 absence: note in Round 2 merge prompt ("上轮 X 缺席,请补查该维度")
- Round 2 absence: note in P5 human fallback ("X 本次未评审,请人工补查")
```

- [ ] **Step 3: Commit**

```bash
git add skills/xteam-design/midcheck-thresholds.md skills/xteam-design/failure-handling.md
git commit -m "feat(xteam): add midcheck thresholds + failure handling rules (M2)

midcheck-thresholds.md codifies the 4 P3.5 signals (spec §3.3).
failure-handling.md codifies the full §5.1 failure table for
orchestrator reference during P3-P6."
```

---

### Task 14: Resume + writeback commands

**Files:**
- Create: `commands/xteam-resume.md`
- Create: `commands/xteam-writeback.md`

- [ ] **Step 1: Write resume command**

`commands/xteam-resume.md`:
```markdown
---
description: "Resume an interrupted xTeam design session from its snapshot"
---

Resume a previously interrupted `/xteam-design` session.

If `$ARGUMENTS` is empty, list recent sessions under `.xteam/` and ask
which to resume.

Otherwise, load `.xteam/$ARGUMENTS/snapshot.json` and resume the
`xteam-design` skill from the phase recorded in the snapshot.
```

- [ ] **Step 2: Write writeback command**

`commands/xteam-writeback.md`:
```markdown
---
description: "Write approved KB diffs back to the knowledge base"
---

Retry a failed or deferred KB writeback for a completed xTeam session.

If `$ARGUMENTS` is empty, ask for a session-id.

Otherwise, load the `kb-diff.md` from the session's output directory
and present each candidate update for human approval. Approved items
are written to KB via MCP (M2: fixture echo only; live MCP in M3).
```

- [ ] **Step 3: Commit**

```bash
git add commands/xteam-resume.md commands/xteam-writeback.md
git commit -m "feat(xteam): add /xteam-resume and /xteam-writeback commands (M2)

resume loads snapshot and re-enters the skill at the saved phase.
writeback retries the P7 KB write for sessions that failed or
were deferred. Spec §3.5, §4.5."
```

---

### Task 15: Output templates

**Files:**
- Create: `templates/xteam/tech-design.md`
- Create: `templates/xteam/plan.md`

- [ ] **Step 1: Write tech-design template**

`templates/xteam/tech-design.md`:
```markdown
# {title} · 技术方案

> 由 xTeam 圆桌生成 · Session: {session_id} · {date}

## 方案概述

{overview}

## 数据模型

{schema}

## 接口契约

{api_contract}

## 失败处理

{failure_modes}

## 迁移与灰度

{migration}

## 监控与告警

{observability}

## 限流与回滚

{rate_limit_and_rollback}

<!-- Conditional sections below — only present when applicable -->
```

- [ ] **Step 2: Write plan template**

`templates/xteam/plan.md`:
```markdown
# {title} Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** {goal}

**Architecture:** {architecture}

**Tech Stack:** {tech_stack}

**Source:** Generated by xTeam design roundtable · Session {session_id}

---

<!-- Tasks generated by plan-composer agent from tech-design.md -->
```

- [ ] **Step 3: Commit**

```bash
git add templates/xteam/tech-design.md templates/xteam/plan.md
git commit -m "docs(xteam): add P6 output templates (M2)

tech-design.md skeleton with all required H2 sections.
plan.md skeleton compatible with writing-plans skill format.
Both are reference templates; actual content comes from agents."
```

---

### Task 16: Extend SKILL.md for P3-P6

**Files:**
- Modify: `skills/xteam-design/SKILL.md`

- [ ] **Step 1: Read current SKILL.md**

Read `skills/xteam-design/SKILL.md` to see M1 content.

- [ ] **Step 2: Append P3-P6 phases after the existing Phase 2 section**

Add after the `### Phase 2 — Draft` section and before `## Files referenced`:

```markdown
### Phase 3 — Round 1

1. For each of the 4 reviewer roles (data, perf, security, qa), compose
   a prompt including:
   - Full PRD frontmatter + body
   - KB snapshot **sliced for role** via `slice_for_role(snap, role)`
   - Current draft (v0 from Phase 2)
   - `round: 1`
   - Must-answer state (applicable items)

2. Dispatch all 4 reviewers **in parallel** via the Agent tool with
   `subagent_type: xteam-agent-<role>`. Each should follow the rules
   in `agents/xteam-agent-<role>.md`.

3. Collect results. For each reviewer:
   - If valid JSON matching `reviewer-output.schema.json`: keep
   - If invalid: re-dispatch once with error appended
   - If second attempt fails: mark reviewer as **absent** for this round

4. Dispatch architect in **merge mode**:
   - Input: v0 draft + all reviewer JSONs from step 3
   - Absent reviewers noted in prompt
   - Instruction: `mode: merge` per `agents/xteam-agent-architect.md`

5. Validate merge output against `architect-merge-output.schema.json`.
   On failure: re-dispatch once. If second attempt fails: snapshot + exit.

6. The merge produces v1 draft. Update snapshot:
   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.session import Session
   from xteam_lib.snapshot import load_snapshot, save_snapshot
   from xteam_lib.roundtable import merge_must_answer_updates
   from pathlib import Path

   session = Session('<session-id>', root=Path('.xteam'))
   snap = load_snapshot(session)
   snap.phase = 'P3-complete'
   snap.drafts['v1'] = '<v1 tech_design_markdown>'
   snap.rounds['round_1'] = {
       'reviewer_outputs': [<list of reviewer JSONs>],
       'merge_changelog': <merge_changelog from architect>,
       'absent_reviewers': [<list of absent role names>],
   }
   # merge must_answer_updates from all sources
   save_snapshot(session, snap)
   "
   ```

### Phase 3.5 — Mid-check

1. Evaluate midcheck thresholds:

   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.roundtable import evaluate_midcheck
   import json
   result = evaluate_midcheck(
       reviewer_outputs=<round 1 reviewer JSONs>,
       merge_output=<architect merge output>,
       must_answer_state=<current must_answer_state>,
   )
   print(json.dumps({'triggered': result.triggered, 'signals': result.signals}))
   "
   ```

2. If `triggered=false`: skip to Phase 4.

3. If `triggered=true`:
   - Collect all questions: reviewer open_questions + merge open_questions
   - Present to user in a batch: "以下问题需要你的输入:"
   - Wait for user responses
   - If user does not respond: save snapshot, exit, suggest `/xteam-resume`

4. Record human responses in snapshot:
   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.kb import merge_temp_layer
   # ... merge human responses into KB temp layer
   "
   ```

5. Update snapshot with human_responses and phase='P3.5-complete'.

### Phase 4 — Round 2

1. Same structure as Phase 3, but:
   - Input base is v1 (not v0)
   - KB includes temp layer from P3.5 (if triggered)
   - Must-answer state reflects Round 1 updates
   - Note absent reviewers from Round 1 in architect merge prompt:
     "上轮 `<role>` 缺席,请补查该维度"

2. Dispatch all 4 reviewers in parallel with `round: 2`.

3. Collect, validate, handle failures (same as P3).

4. Dispatch architect merge → v2.

5. Update snapshot: phase='P4-complete', drafts['v2'], rounds['round_2'].

### Phase 5 — Converge

1. Check for unresolved items after Round 2:
   - Must-answer items still `missing` with `applicable=true`
   - Remaining open_questions_for_human
   - Absent reviewers from Round 2

2. If no unresolved items: skip to Phase 6 with v_final = v2.

3. If unresolved items exist:
   - Count total questions for human
   - If > 20: exit with "PRD 尚不成熟,建议先用 brainstorming 完善"
   - Present unresolved items to user
   - Wait for responses
   - Dispatch architect merge (mode=merge) with v2 + human responses → v_final

4. Update snapshot: phase='P5-complete', drafts['v_final'].

### Phase 6 — Output

1. Write tech-design.md:
   - Path: `<prd-dir>/../design/<prd-basename>.tech-design.md`
   - Content: v_final tech_design_markdown

2. Dispatch plan-composer agent:
   - Input: v_final + PRD frontmatter
   - Subagent: `xteam-agent-plan-composer`
   - Output: plan.md content

3. Write plan.md:
   - Path: `<prd-dir>/../design/<prd-basename>.plan.md`

4. Generate kb-diff:
   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.kb_diff import extract_kb_diff_candidates
   import json
   diff = extract_kb_diff_candidates(
       session_id='<session-id>',
       merge_changelogs=[<round1_changelog>, <round2_changelog>],
       human_responses=<all human responses>,
   )
   print(json.dumps(diff, ensure_ascii=False, indent=2))
   "
   ```

5. Write kb-diff.md:
   - Path: `<prd-dir>/../design/<prd-basename>.kb-diff.md`
   - Format as human-readable YAML block

6. Update snapshot: phase='P6-complete'.

7. Tell the user:
   > 圆桌完成。产物:
   > - 技术方案: `<tech-design path>`
   > - 任务拆解: `<plan path>`
   > - KB 更新候选: `<kb-diff path>` (需人审后执行 `/xteam-writeback`)
   >
   > Must-answer: N applicable, M draft, K n/a.
   > Open questions resolved: X. Human interventions: Y.
```

- [ ] **Step 3: Update the description in the frontmatter**

Change the skill description from M1-only to full scope:
```yaml
description: |
  xTeam design roundtable orchestrator. Phases 0-6:
  P0 PRD intake, P1 KB fetch, P2 architect draft,
  P3 Round 1 (4 reviewers + merge), P3.5 Mid-check,
  P4 Round 2, P5 Converge, P6 Output.
  P7 KB writeback is via /xteam-writeback command.
```

- [ ] **Step 4: Update the "Files referenced" and "Not in M1" sections**

Replace `## Not in M1` with:
```markdown
## Not in M2

- Live MCP KB (uses fixtures) — M3
- P7 KB writeback execution — M3
- Resume from snapshot — M3
- Metrics dashboard + golden test suite — M3
- `/xteam-record-final` metrics registration — M3
```

- [ ] **Step 5: Commit**

```bash
git add skills/xteam-design/SKILL.md
git commit -m "feat(xteam): extend orchestrator skill for P3-P6 (M2)

Adds complete roundtable flow: parallel reviewer dispatch (P3/P4),
midcheck evaluation (P3.5), human convergence (P5), and structured
output with plan-composer (P6). KB still uses fixtures (MCP in M3)."
```

---

### Task 17: M2 smoke test

**Files:**
- Create: `tests/xteam/unit/test_m2_smoke.py`

- [ ] **Step 1: Write the test**

`tests/xteam/unit/test_m2_smoke.py`:
```python
"""M2 deterministic pipeline smoke test.

Tests the Python side of M2: reviewer output loading, midcheck eval,
must-answer merging, KB temp layer, kb-diff generation, snapshot with
rounds. Does NOT test LLM dispatch (that lives in SKILL.md).
"""
import json
from pathlib import Path

from xteam_lib.kb import load_kb_from_fixtures, merge_temp_layer, slice_for_role
from xteam_lib.kb_diff import extract_kb_diff_candidates
from xteam_lib.must_answer import compute_applicability, load_canonical_items
from xteam_lib.prd import parse_prd, validate_prd
from xteam_lib.roundtable import evaluate_midcheck, merge_must_answer_updates, collect_all_questions
from xteam_lib.schema_validate import validate_against
from xteam_lib.session import Session, new_session_id
from xteam_lib.snapshot import Snapshot, save_snapshot, load_snapshot


def test_m2_full_pipeline(fixtures_dir: Path, tmp_xteam_root: Path):
    # Phase 0: parse + validate
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    validate_prd(prd)

    # Phase 1: applicability + KB
    state = compute_applicability(prd, load_canonical_items())
    must_answer = {k: {"applicable": v.applicable, "status": v.status} for k, v in state.items()}
    module_names = [m["name"] for m in prd.frontmatter["involved_modules"]]
    kb_snap = load_kb_from_fixtures(module_names, fixtures_dir / "kb")

    # Phase 2 would dispatch architect — simulate v0
    v0_draft = "## 方案概述\ntest draft content" + "x" * 100

    # Phase 3: load fixture reviewer outputs
    reviewer_outputs = []
    for name in ["data-round1-changes-requested", "perf-round1-approved",
                  "security-round1-block", "qa-round1-changes-requested"]:
        with open(fixtures_dir / "reviewer" / f"{name}.json") as f:
            ro = json.load(f)
        validate_against(ro, "reviewer-output")
        reviewer_outputs.append(ro)

    # Simulate merge output
    merge_output = {
        "mode": "merge",
        "tech_design_markdown": v0_draft + "\n## Updated sections",
        "must_answer_updates": [{"id": "schema", "status": "draft"}],
        "merge_changelog": [
            {"action": "fixed", "source_role": "data", "severity": "critical",
             "summary": "Added unique index on rec_candidates" + " " * 20},
            {"action": "escalated", "source_role": "security", "severity": "critical",
             "summary": "Auth requirement needs business decision" + " " * 20},
        ],
        "open_questions_for_human": ["需确认推荐理由是否属于PII"],
        "unresolvable_conflicts": [],
    }

    # Merge must-answer updates
    all_updates = [ro["must_answer_updates"] for ro in reviewer_outputs]
    all_updates.append(merge_output["must_answer_updates"])
    updated_state = merge_must_answer_updates(must_answer, all_updates)

    # Phase 3.5: midcheck
    midcheck = evaluate_midcheck(reviewer_outputs, merge_output, updated_state)
    # With 4 reviewer questions + 1 merge question ≥ 5, plus 1 escalated critical
    assert midcheck.triggered is True
    assert len(midcheck.signals) >= 1

    # Simulate human responses
    human_responses = [{"content": "推荐理由不属于PII,无需脱敏", "source_phase": "P3.5"}]
    merged_kb = merge_temp_layer(kb_snap, human_responses)
    assert "temp" in merged_kb.source

    # KB slicing still works on merged snapshot
    data_slice = slice_for_role(merged_kb, "data")
    assert "comment" in data_slice

    # Phase 4/5 would repeat — skip to P6 output

    # KB diff generation
    kb_diff = extract_kb_diff_candidates(
        session_id="test-m2",
        merge_changelogs=[merge_output["merge_changelog"]],
        human_responses=human_responses,
    )
    validate_against(kb_diff, "kb-diff")
    assert len(kb_diff["candidate_updates"]) >= 2  # fixed + escalated + human

    # Snapshot with rounds
    session = Session(new_session_id(), root=tmp_xteam_root)
    snap = Snapshot(
        session_id=session.id,
        phase="P6-complete",
        prd_path=str(prd.source_path),
        kb_snapshot=kb_snap.to_dict(),
        drafts={"v0": v0_draft, "v1": merge_output["tech_design_markdown"]},
        rounds={
            "round_1": {
                "reviewer_outputs": reviewer_outputs,
                "merge_changelog": merge_output["merge_changelog"],
                "absent_reviewers": [],
            },
        },
        must_answer_state=updated_state,
        human_responses=human_responses,
    )
    save_snapshot(session, snap)

    # Reload and verify
    loaded = load_snapshot(session)
    assert loaded.phase == "P6-complete"
    assert len(loaded.rounds["round_1"]["reviewer_outputs"]) == 4
    assert loaded.human_responses[0]["content"] == "推荐理由不属于PII,无需脱敏"
```

- [ ] **Step 2: Run test**

Run: `source .venv/bin/activate && python -m pytest tests/xteam/unit/test_m2_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 3: Run full suite**

Run: `source .venv/bin/activate && python -m pytest tests/xteam -v`
Expected: All tests pass (M1 + M2, ~50+ tests).

- [ ] **Step 4: Commit**

```bash
git add tests/xteam/unit/test_m2_smoke.py
git commit -m "test(xteam): add M2 full pipeline smoke test

Exercises the complete deterministic pipeline: reviewer output
loading + schema validation, must-answer merging, midcheck
evaluation, KB temp layer merge, KB diff generation, and snapshot
with rounds. Confirms all M2 Python modules integrate correctly."
```

---

### Task 18: M2 verification gate

**Files:** (no new files)

- [ ] **Step 1: Full test suite green**

Run: `source .venv/bin/activate && python -m pytest tests/xteam -v`
Expected: All tests pass.

- [ ] **Step 2: Manual skill run**

In Claude Code, restart session then run:
```
/xteam-design tests/xteam/fixtures/prd/valid-minimal.md
```

Expected: Full roundtable runs (P0→P6):
- P0: PRD validates
- P1: KB loads (comment + feed)
- P2: Architect draft v0
- P3: 4 reviewers dispatched, merge → v1
- P3.5: Midcheck evaluates (may or may not trigger)
- P4: Round 2, merge → v2
- P5: Converge (if needed)
- P6: tech-design.md + plan.md + kb-diff.md written

- [ ] **Step 3: Verify output files exist**

Check:
- `tests/xteam/fixtures/design/valid-minimal.tech-design.md`
- `tests/xteam/fixtures/design/valid-minimal.plan.md`
- `tests/xteam/fixtures/design/valid-minimal.kb-diff.md`
- `.xteam/<session-id>/snapshot.json` (phase = P6-complete)

---

## Self-Review

### 1. Spec coverage

| Spec section | M2 task(s) |
|---|---|
| §2.3 reviewer output schema | Task 1 |
| §2.4 architect merge mode | Task 2 (schema), Task 5 (prompt) |
| §2.5 plan-composer | Task 6 |
| §3.2 P3 Round 1 flow | Task 16 (SKILL.md) |
| §3.3 P3.5 midcheck thresholds | Task 8 (Python), Task 13 (skill file) |
| §3.2 P4 Round 2 flow | Task 16 |
| §3.2/§3.4 P5 Converge | Task 16 |
| §3.2 P6 Output | Task 16 |
| §4.1 KB temp layer | Task 11 |
| §4.4 kb-diff structure | Task 3 (schema), Task 12 (Python) |
| §5.1 failure handling | Task 13 (skill file), Task 16 (SKILL.md) |
| §5.2 snapshot rounds | Task 10 |
| §7.2 resume/writeback commands | Task 14 |
| §7.2 output templates | Task 15 |

**Not in M2 (deferred to M3):** §4.5 live MCP, §6.3 component tests, §6.4 golden suite, §6.5-§6.7 metrics, P7 writeback execution, `/xteam-record-final`.

### 2. Placeholder scan

No TBDs, "implement later", or "similar to Task N" found. Task 14 commands are thin shells (expected — the skill does the real work). Task 15 templates use `{placeholder}` syntax — this is intentional template syntax, not missing content.

### 3. Type consistency

- `MidcheckResult(triggered, signals, all_questions)` — consistent in Task 8 tests and implementation
- `Snapshot.rounds` — dict[str, dict[str, Any]], used in Tasks 10, 16, 17
- `KBSnapshot.temp_layer` — list[dict[str, Any]], used in Task 11
- `merge_must_answer_updates(state, updates_list)` — signature consistent across Tasks 8, 9, 17
- Schema names: `reviewer-output`, `architect-merge-output`, `kb-diff` — all match file names in schemas/xteam/
