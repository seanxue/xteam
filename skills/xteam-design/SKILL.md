---
name: xteam-design
description: |
  M1 scope — Phase 0 PRD intake, Phase 1 KB fetch (fixture in M1, MCP in M2),
  Phase 2 architect draft. Terminates with a v0 tech-design markdown file
  and a snapshot. Rounds / mid-check / converge / outputs / writeback are
  out of scope for M1 (see docs/xteam/plans/ for M2 & M3).
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

## Files referenced

- `skills/xteam-design/must-answer-items.md` — canonical must-answer list
- `agents/xteam-agent-architect.md` — subagent prompt
- `schemas/xteam/*` — all I/O schemas
- `xteam_lib/` — deterministic helpers

## Not in M1

- Reviewer agents (data/perf/security/qa) — M2
- Round 1/2, P3.5, P5 — M2
- plan-composer + plan.md — M2
- kb-diff + P7 writeback — M3
- Resume / metrics / golden test suite — M3
