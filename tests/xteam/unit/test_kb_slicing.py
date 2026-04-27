from pathlib import Path

import pytest

from xteam_lib.kb import load_kb_from_fixtures, slice_for_role


@pytest.fixture
def snap(fixtures_dir: Path):
    return load_kb_from_fixtures(["comment", "feed"], fixtures_dir / "kb")


def test_architect_gets_full_snapshot(snap):
    sliced = slice_for_role(snap, "architect")
    assert sliced == snap.modules  # architect sees everything


def test_data_role_filters_to_data_concerns(snap):
    sliced = slice_for_role(snap, "data")
    comment = sliced["comment"]
    # data_stores kept
    assert "data_stores" in comment["module_profile"]
    # capacity dropped (perf concern)
    assert "capacity" not in comment["module_profile"]
    # only schema/migration pitfalls kept
    pfs = comment["historical_pitfalls"]
    assert all(
        {"schema", "migration"} & set(p.get("categories", []))
        for p in pfs
    )


def test_perf_role_filters_to_perf_concerns(snap):
    sliced = slice_for_role(snap, "perf")
    comment = sliced["comment"]
    assert "capacity" in comment["module_profile"]
    assert "data_stores" not in comment["module_profile"]
    pfs = comment["historical_pitfalls"]
    assert all(
        {"hotspot", "cache"} & set(p.get("categories", []))
        for p in pfs
    )


def test_security_role_filters_to_security_concerns(snap):
    sliced = slice_for_role(snap, "security")
    comment = sliced["comment"]
    # conventions.security kept; conventions.data dropped
    convs = comment.get("conventions", {})
    assert "security" in convs
    assert "data" not in convs


def test_qa_role_filters_to_qa_concerns(snap):
    sliced = slice_for_role(snap, "qa")
    comment = sliced["comment"]
    assert "test_strategy" in comment["module_profile"]
    assert "conventions" in comment
    assert "testing" in comment["conventions"]
    assert "data" not in comment["conventions"]


def test_unknown_role_raises(snap):
    with pytest.raises(ValueError, match="unknown role"):
        slice_for_role(snap, "coder")
