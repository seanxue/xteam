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
    validate_against(result, "kb-diff")


def test_empty_inputs_produce_empty_diff():
    result = extract_kb_diff_candidates(
        session_id="test",
        merge_changelogs=[],
        human_responses=[],
    )
    assert result["candidate_updates"] == []
    validate_against(result, "kb-diff")
