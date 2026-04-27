"""Single entry point for JSON schema validation.

All xteam I/O contracts live in schemas/xteam/<name>.schema.json.
Callers pass the short name (e.g. "prd"); this module resolves the file
and runs jsonschema Draft-07 validation.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, ValidationError


_SCHEMAS_DIR = Path(__file__).parents[1] / "schemas" / "xteam"


class SchemaNotFound(FileNotFoundError):
    pass


@lru_cache(maxsize=None)
def _load(name: str) -> Draft7Validator:
    path = _SCHEMAS_DIR / f"{name}.schema.json"
    if not path.exists():
        raise SchemaNotFound(f"schema not found: {path}")
    with path.open() as f:
        schema = json.load(f)
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def validate_against(payload: Any, schema_name: str) -> None:
    """Raise ValueError with joined error messages if invalid."""
    validator = _load(schema_name)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.absolute_path)
    if errors:
        msgs = [_format(e) for e in errors]
        raise ValueError("schema validation failed: " + "; ".join(msgs))


def _format(err: ValidationError) -> str:
    loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{loc}: {err.message}"
