"""Must-answer item applicability and status tracking.

The canonical list lives in skills/xteam-design/must-answer-items.md,
embedded as a YAML block between ```yaml fences. We parse that block
to avoid duplicating the definition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from xteam_lib.prd import PRD


_CANONICAL_MD = (
    Path(__file__).parents[1] / "skills" / "xteam-design" / "must-answer-items.md"
)

_YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.DOTALL)

_VALID_STATUS = {"missing", "draft", "n/a"}


@dataclass
class MustAnswerItem:
    id: str
    applies_when: str
    owners: list[str]
    description: str
    applicable: bool = False
    status: str = "missing"


def load_canonical_items() -> list[MustAnswerItem]:
    text = _CANONICAL_MD.read_text()
    match = _YAML_BLOCK.search(text)
    if not match:
        raise RuntimeError(f"no yaml block in {_CANONICAL_MD}")
    data = yaml.safe_load(match.group(1))
    return [
        MustAnswerItem(
            id=item["id"],
            applies_when=item["applies_when"],
            owners=list(item["owners"]),
            description=item["description"],
        )
        for item in data["items"]
    ]


def compute_applicability(
    prd: PRD, items: Iterable[MustAnswerItem]
) -> dict[str, MustAnswerItem]:
    fm = prd.frontmatter
    has_legacy_core = any(
        m.get("kind") == "legacy" and m.get("touches_core_feature")
        for m in fm.get("involved_modules", [])
    )
    business_type = fm.get("business_type")

    state: dict[str, MustAnswerItem] = {}
    for item in items:
        # shallow copy to avoid mutating caller's list
        copy = MustAnswerItem(
            id=item.id,
            applies_when=item.applies_when,
            owners=list(item.owners),
            description=item.description,
        )
        copy.applicable = _evaluate(
            item.applies_when,
            has_legacy_core=has_legacy_core,
            business_type=business_type,
        )
        state[item.id] = copy
    return state


def _evaluate(
    applies_when: str, *, has_legacy_core: bool, business_type: str | None
) -> bool:
    if applies_when == "always":
        return True
    if applies_when == "involved_legacy_core_module":
        return has_legacy_core
    if applies_when == "business_type_content_social":
        return business_type == "content_social"
    raise ValueError(f"unknown applies_when: {applies_when!r}")
