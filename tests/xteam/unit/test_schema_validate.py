from pathlib import Path

import pytest

from xteam_lib.schema_validate import validate_against, SchemaNotFound


REPO = Path(__file__).parents[3]


def test_validates_minimal_prd_frontmatter_payload():
    payload = {
        "title": "Add comment reactions",
        "background": "Users want to express reactions beyond like.",
        "goal": "Ship 6 reactions with content-safety gating.",
        "user_scenarios": ["User taps react on a comment"],
        "features": [{"id": "F1", "summary": "Reaction picker UI"}],
        "metrics": ["reaction dau uplift"],
        "out_of_scope": [],
        "involved_modules": [
            {"name": "comment", "kind": "legacy", "touches_core_feature": True}
        ],
    }
    validate_against(payload, "prd")  # no exception


def test_rejects_prd_missing_required_field():
    payload = {"title": "x"}
    with pytest.raises(ValueError, match="required"):
        validate_against(payload, "prd")


def test_unknown_schema_raises_schema_not_found():
    with pytest.raises(SchemaNotFound):
        validate_against({}, "nonexistent")
