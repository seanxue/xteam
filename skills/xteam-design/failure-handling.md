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
