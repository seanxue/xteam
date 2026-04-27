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
