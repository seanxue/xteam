---
name: xteam-design
description: |
  xTeam design roundtable orchestrator. Phases 0-6:
  P0 PRD intake, P1 KB fetch, P2 architect draft,
  P3 Round 1 (4 reviewers + merge), P3.5 Mid-check,
  P4 Round 2, P5 Converge, P6 Output.
  P7 KB writeback is via /xteam-writeback command.
---

# xTeam Design · M1 Skeleton Walkthrough

Your role in this skill is the **orchestrator** (spec §1.2): a Claude
Code session running this playbook, not a subagent. You call Python
utilities for deterministic work and dispatch the architect subagent
via the Agent tool.

## When to use

Invoked by `/xteam-design <prd-path>`. If the user invokes this skill
directly without a path, ask for the PRD path once and stop if they
don't provide one.

## M1 execution

### Phase 0 — Intake

1. Read the PRD file at the given path and validate it:

   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.prd import parse_prd, validate_prd
   p = parse_prd('<prd-path>')
   validate_prd(p)
   print('OK:', p.frontmatter['title'])
   "
   ```

   - On non-zero exit: show the error (it comes from `PRDInvalid`),
     explain what's missing, and stop. Do not proceed.

2. On success, generate a session id and prepare paths:

   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.session import Session, new_session_id
   from pathlib import Path
   sid = new_session_id()
   s = Session(sid, root=Path('.xteam'))
   s.ensure_dir()
   print(sid)
   "
   ```

### Phase 1 — Context

1. Compute must-answer applicability:

   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.prd import parse_prd
   from xteam_lib.must_answer import compute_applicability, load_canonical_items
   import json
   p = parse_prd('<prd-path>')
   state = compute_applicability(p, load_canonical_items())
   print(json.dumps({k: {'applicable': v.applicable, 'status': v.status, 'description': v.description} for k, v in state.items()}, ensure_ascii=False, indent=2))
   "
   ```

   Inspect the result. Note which `must_answer` items are `applicable=true`.

2. **M1: load KB from fixtures** (not MCP). For each module in
   `prd.frontmatter.involved_modules`, verify that the fixture file
   exists. Load the KB:

   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.kb import load_kb_from_fixtures
   from pathlib import Path
   import json
   snap = load_kb_from_fixtures(
     modules=['<module1>', '<module2>'],
     fixtures_dir=Path('tests/xteam/fixtures/kb'),
   )
   print('KB modules:', sorted(snap.modules.keys()))
   print(json.dumps(snap.to_dict(), ensure_ascii=False, indent=2)[:500])
   "
   ```

   If any module fixture is missing, tell the user:
   > M1 uses fixture KB. Module `<name>` has no fixture at
   > `tests/xteam/fixtures/kb/module-<name>.yaml`. Create one modelled
   > on `module-comment.yaml` and retry.

   Then stop.

3. Save initial snapshot:

   ```bash
   source .venv/bin/activate && python -c "
   import json
   from xteam_lib.prd import parse_prd
   from xteam_lib.kb import load_kb_from_fixtures
   from xteam_lib.must_answer import compute_applicability, load_canonical_items
   from xteam_lib.session import Session
   from xteam_lib.snapshot import Snapshot, save_snapshot
   from pathlib import Path

   prd = parse_prd(Path('<prd-path>'))
   modules = [m['name'] for m in prd.frontmatter['involved_modules']]
   kb = load_kb_from_fixtures(modules, Path('tests/xteam/fixtures/kb'))
   state = compute_applicability(prd, load_canonical_items())

   session = Session('<session-id>', root=Path('.xteam'))
   snap = Snapshot(
       session_id=session.id,
       phase='P1-complete',
       prd_path=str(prd.source_path),
       kb_snapshot=kb.to_dict(),
       must_answer_state={k: {'applicable': v.applicable, 'status': v.status} for k, v in state.items()},
   )
   save_snapshot(session, snap)
   print('Snapshot saved:', session.snapshot_path)
   "
   ```

### Phase 2 — Draft

1. Compose the architect subagent prompt. Include in the prompt:
   - Full PRD frontmatter + body
   - Full KB snapshot (architect gets everything per spec §4.3)
   - Must-answer state (which items are applicable)
   - Instruction: `mode: draft`

2. Dispatch via the **Agent tool** with subagent description referencing
   `xteam-agent-architect`. The prompt should instruct the agent to
   follow the rules in `agents/xteam-agent-architect.md`.

3. The subagent returns a fenced JSON block. Extract it and validate:

   ```bash
   source .venv/bin/activate && python -c "
   import json
   from xteam_lib.schema_validate import validate_against
   payload = json.loads('''<paste the JSON here>''')
   validate_against(payload, 'architect-draft-output')
   print('Schema OK')
   "
   ```

   On validation failure: re-dispatch once with the error appended.
   If second attempt also fails, save snapshot with `last_error` and
   exit with error.

4. Write the draft to disk:
   - Create `<prd-dir>/../design/` directory if needed
   - Write `<prd-basename>.tech-design.md` with the `tech_design_markdown`
     content from the architect's response.

5. Update and save snapshot:

   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.session import Session
   from xteam_lib.snapshot import load_snapshot, save_snapshot
   from pathlib import Path

   session = Session('<session-id>', root=Path('.xteam'))
   snap = load_snapshot(session)
   snap.phase = 'P2-complete'
   snap.drafts['v0'] = '''<tech_design_markdown content>'''
   # merge must_answer_updates from architect response into snap.must_answer_state
   save_snapshot(session, snap)
   print('Phase 2 complete')
   "
   ```

6. Tell the user:
   > M1 draft complete. Output: `<path>`.
   > Must-answer state: N applicable, M draft, K missing.
   > Rounds of review, mid-check, and final plan.md are M2/M3.

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
   from xteam_lib.roundtable import merge_must_answer_updates
   import json
   # merge must_answer_updates from all reviewer outputs + architect merge
   all_updates = [<reviewer1_updates>, <reviewer2_updates>, ..., <merge_updates>]
   updated_state = merge_must_answer_updates(<current_state>, all_updates)
   print(json.dumps(updated_state, ensure_ascii=False, indent=2))
   "
   ```

   Save snapshot with phase='P3-complete', drafts['v1'], rounds['round_1'].

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
   - List each question numbered
   - Wait for user responses
   - If user does not respond: save snapshot, exit, suggest `/xteam-resume`

4. Record human responses and merge into KB temp layer:

   ```bash
   source .venv/bin/activate && python -c "
   from xteam_lib.kb import merge_temp_layer, load_kb_from_fixtures
   # merged_kb = merge_temp_layer(kb_snap, human_responses)
   # This merged_kb is used for Round 2 dispatch
   "
   ```

5. Update snapshot with human_responses and phase='P3.5-complete'.

### Phase 4 — Round 2

1. Same structure as Phase 3, but:
   - Input base is **v1** (not v0)
   - KB includes **temp layer from P3.5** (if triggered)
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

## Files referenced

- `skills/xteam-design/must-answer-items.md` — canonical must-answer list
- `agents/xteam-agent-architect.md` — subagent prompt
- `schemas/xteam/*` — all I/O schemas
- `xteam_lib/` — deterministic helpers
- `skills/xteam-design/midcheck-thresholds.md` — P3.5 threshold config
- `skills/xteam-design/failure-handling.md` — failure disposition rules
- `agents/xteam-agent-data.md` — data reviewer
- `agents/xteam-agent-perf.md` — perf reviewer
- `agents/xteam-agent-security.md` — security reviewer
- `agents/xteam-agent-qa.md` — qa reviewer
- `agents/xteam-agent-plan-composer.md` — P6 format converter

## Not in M2

- Live MCP KB (uses fixtures) — M3
- P7 KB writeback execution — M3
- Resume from snapshot — M3
- Metrics dashboard + golden test suite — M3
- `/xteam-record-final` metrics registration — M3
