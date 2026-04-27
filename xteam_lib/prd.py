"""PRD parsing and validation.

Input format (v1 hard-constrained):
  ---
  <YAML frontmatter matching schemas/xteam/prd.schema.json>
  ---
  # <free-form Markdown body>

parse_prd(path) -> PRD splits the two halves, YAML-loads the frontmatter,
but does NOT yet schema-validate (see validate_prd).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from xteam_lib.errors import PRDInvalid
from xteam_lib.schema_validate import validate_against


@dataclass(frozen=True)
class PRD:
    frontmatter: dict[str, Any]
    body: str
    source_path: Path


def parse_prd(path: Path) -> PRD:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ValueError(f"missing frontmatter opener in {path}")
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        raise ValueError(f"unclosed frontmatter in {path}")
    fm_raw = rest[:end]
    body = rest[end + 5 :]
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML frontmatter in {path}: {e}") from e
    return PRD(frontmatter=fm, body=body.lstrip(), source_path=path)


def validate_prd(prd: PRD) -> None:
    """Schema-validate plus heuristic 'is this really a PRD?' check.

    Raises PRDInvalid with actionable messages for the user.

    Order of checks:
    1. Heuristic first: if features/user_scenarios are *present but empty*,
       give a human-friendly "idea not PRD" error rather than a dry schema
       message.  Missing fields are intentionally left for schema to catch
       (step 2) so callers get a complete list of what's absent.
    2. Schema validation: reports all missing/invalid fields.
    """
    fm = prd.frontmatter
    # Heuristic: fields present but vacuous → treat as idea, not spec.
    # (missing fields fall through to schema validation below)
    if ("features" in fm and not fm["features"]) or (
        "user_scenarios" in fm and not fm["user_scenarios"]
    ):
        raise PRDInvalid(
            "PRD appears to be an idea, not a shippable spec "
            "(features or user_scenarios empty). "
            "Use superpowers:brainstorming to shape it first."
        )

    try:
        validate_against(prd.frontmatter, "prd")
    except ValueError as e:
        raise PRDInvalid(str(e)) from e
