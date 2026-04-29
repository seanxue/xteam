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
