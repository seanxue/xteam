from pathlib import Path

import pytest

from xteam_lib.errors import PRDInvalid
from xteam_lib.prd import parse_prd, validate_prd


def test_valid_prd_passes(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    validate_prd(prd)  # no raise


def test_missing_required_fields_raises(fixtures_dir: Path):
    prd = parse_prd(fixtures_dir / "prd" / "invalid-missing-fields.md")
    with pytest.raises(PRDInvalid) as exc:
        validate_prd(prd)
    msg = str(exc.value)
    # each missing top-level field shows up in one message
    assert "background" in msg
    assert "user_scenarios" in msg
    assert "features" in msg


def test_idea_style_prd_is_rejected_as_too_thin(fixtures_dir: Path):
    """When features=[] or user_scenarios=[], treat as 'idea, not PRD'."""
    prd = parse_prd(fixtures_dir / "prd" / "idea-not-prd.md")
    with pytest.raises(PRDInvalid, match="appears to be an idea"):
        validate_prd(prd)
