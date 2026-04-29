# P3.5 Midcheck Thresholds

> v1 hardcoded values. After 4 weeks of real usage, move to `.xteam/config.yml`
> and set based on P75 of observed values. Spec §3.3.

| Signal | Threshold | Description |
|--------|-----------|-------------|
| `open_questions_for_human` total across all reviewers + merge | >= 5 | Too many unknowns for confident design |
| Escalated `critical` issues in merge_changelog | >= 1 | Architect could not resolve a blocking issue |
| `applicable=true` must-answer items still `missing` after merge | >= 3 | Draft is not covering required dimensions |
| `unresolvable_conflicts` in merge output | >= 2 | Reviewers fundamentally disagree on approach |

**Any single threshold exceeded -> trigger P3.5.** All signals are batched
into one human interaction (spec §3.4: reviewers never ask humans directly).

These values are also defined in `xteam_lib/roundtable.py` as constants.
Changing them requires updating both locations until config extraction.
