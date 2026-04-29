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
    assert result["schema"]["status"] == "draft"
    assert result["migration"]["status"] == "draft"
    assert result["observability"]["status"] == "draft"
    assert result["content_safety"]["status"] == "draft"
    assert result["failure_modes"]["status"] == "draft"
    assert result["rollback"]["status"] == "draft"
