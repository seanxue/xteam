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
    original_source = snap.source
    merge_temp_layer(snap, [{"content": "test"}])
    # Original snap unchanged (frozen dataclass)
    assert snap.source == original_source


def test_merge_with_empty_responses_is_noop(fixtures_dir: Path):
    snap = load_kb_from_fixtures(["comment"], fixtures_dir / "kb")
    merged = merge_temp_layer(snap, [])
    assert merged.source == "fixture"
    assert merged.temp_layer == []
