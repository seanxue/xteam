"""Roundtable evaluation helpers.

Deterministic functions used by the orchestrator (SKILL.md) during
Phases 3-5. All LLM reasoning stays in skills/agents — this module
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

    # Signal 1: open_questions across all reviewers >= 5
    all_questions: list[str] = []
    for ro in reviewer_outputs:
        all_questions.extend(ro.get("open_questions_for_human", []))
    all_questions.extend(merge_output.get("open_questions_for_human", []))
    if len(all_questions) >= THRESHOLD_OPEN_QUESTIONS:
        signals.append(
            f"open_questions: {len(all_questions)} >= {THRESHOLD_OPEN_QUESTIONS}"
        )

    # Signal 2: critical issues escalated (not fixed) >= 1
    escalated_criticals = sum(
        1
        for entry in merge_output.get("merge_changelog", [])
        if entry.get("action") == "escalated" and entry.get("severity") == "critical"
    )
    if escalated_criticals >= THRESHOLD_UNRESOLVED_CRITICALS:
        signals.append(
            f"unresolved_critical: {escalated_criticals} >= {THRESHOLD_UNRESOLVED_CRITICALS}"
        )

    # Signal 3: applicable must-answer items still missing >= 3
    missing_count = sum(
        1
        for v in must_answer_state.values()
        if v.get("applicable") and v.get("status") == "missing"
    )
    if missing_count >= THRESHOLD_MISSING_MUST_ANSWERS:
        signals.append(
            f"missing_must_answer: {missing_count} >= {THRESHOLD_MISSING_MUST_ANSWERS}"
        )

    # Signal 4: unresolvable conflicts >= 2
    conflict_count = len(merge_output.get("unresolvable_conflicts", []))
    if conflict_count >= THRESHOLD_UNRESOLVABLE_CONFLICTS:
        signals.append(
            f"unresolvable_conflict: {conflict_count} >= {THRESHOLD_UNRESOLVABLE_CONFLICTS}"
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
                # Only upgrade: missing -> draft, missing -> n/a
                if old_status == "missing" or new_status in ("draft", "n/a"):
                    state[item_id]["status"] = new_status
    return state
