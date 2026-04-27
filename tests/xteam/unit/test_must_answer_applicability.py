from pathlib import Path

from xteam_lib.must_answer import MustAnswerItem, compute_applicability, load_canonical_items
from xteam_lib.prd import parse_prd


def test_canonical_list_has_11_items():
    items = load_canonical_items()
    assert len(items) == 11
    ids = {i.id for i in items}
    assert "schema" in ids
    assert "compat_and_isolation" in ids
    assert "hotspot" in ids


def test_always_items_always_applicable(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    state = compute_applicability(prd, load_canonical_items())
    assert state["schema"].applicable is True
    assert state["api_contract"].applicable is True
    assert state["rollback"].applicable is True


def test_compat_applies_when_legacy_core_module_present(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    # comment is kind=legacy + touches_core_feature=true
    state = compute_applicability(prd, load_canonical_items())
    assert state["compat_and_isolation"].applicable is True


def test_compat_skipped_when_only_new_modules(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-new-module-only.md")
    state = compute_applicability(prd, load_canonical_items())
    assert state["compat_and_isolation"].applicable is False


def test_content_social_items_applicable_when_business_type_matches(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    state = compute_applicability(prd, load_canonical_items())
    for key in ("content_safety", "cache_strategy", "hotspot"):
        assert state[key].applicable is True


def test_items_initial_status_is_missing(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    state = compute_applicability(prd, load_canonical_items())
    for item in state.values():
        assert item.status == "missing"
