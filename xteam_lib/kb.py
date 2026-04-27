"""KB snapshot loading.

M1: load from YAML fixture files under tests/xteam/fixtures/kb/.
M2: replace load_kb_from_fixtures with a live MCP adapter that
    satisfies the same KBSnapshot interface.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from xteam_lib.errors import KBUnreachable


@dataclass(frozen=True)
class KBSnapshot:
    fetched_at: str
    source: str  # "fixture" | "mcp"
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_kb_from_fixtures(
    modules: Iterable[str], fixtures_dir: Path
) -> KBSnapshot:
    """Load each module's YAML fixture. Raise KBUnreachable if any is missing."""
    collected: dict[str, dict[str, Any]] = {}
    for name in modules:
        path = fixtures_dir / f"module-{name}.yaml"
        if not path.exists():
            raise KBUnreachable(f"no fixture for module {name!r} at {path}")
        with path.open() as f:
            collected[name] = yaml.safe_load(f) or {}
    return KBSnapshot(
        fetched_at=_now_iso(),
        source="fixture",
        modules=collected,
    )
