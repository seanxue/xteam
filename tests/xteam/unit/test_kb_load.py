from pathlib import Path

import pytest

from xteam_lib.errors import KBUnreachable
from xteam_lib.kb import load_kb_from_fixtures


def test_loads_requested_modules(fixtures_dir: Path):
    snap = load_kb_from_fixtures(
        modules=["comment", "feed"],
        fixtures_dir=fixtures_dir / "kb",
    )
    assert snap.source == "fixture"
    assert set(snap.modules.keys()) == {"comment", "feed"}
    assert snap.modules["comment"]["module_profile"]["tech_stack"].startswith("Go")
    assert snap.modules["feed"]["module_profile"]["data_stores"][0].startswith("ClickHouse")
    assert snap.fetched_at  # ISO timestamp


def test_missing_fixture_is_kb_unreachable(fixtures_dir: Path):
    with pytest.raises(KBUnreachable, match="no fixture"):
        load_kb_from_fixtures(
            modules=["nonexistent"],
            fixtures_dir=fixtures_dir / "kb",
        )


def test_snapshot_validates_against_schema(fixtures_dir: Path):
    """load_kb_from_fixtures must return a snapshot that passes its own schema."""
    from xteam_lib.schema_validate import validate_against

    snap = load_kb_from_fixtures(
        modules=["comment"],
        fixtures_dir=fixtures_dir / "kb",
    )
    validate_against(snap.to_dict(), "kb-snapshot")
