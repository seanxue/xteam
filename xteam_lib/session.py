"""Session identity and filesystem layout.

A session represents one end-to-end xteam-design invocation. Its state
lives under `.xteam/<session-id>/` at the repo root by default, but
tests pass a custom root.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

_VALID_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def new_session_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class Session:
    id: str
    root: Path

    def __post_init__(self):
        if not _VALID_ID.match(self.id):
            raise ValueError(f"invalid session id: {self.id!r}")

    @property
    def dir(self) -> Path:
        return self.root / self.id

    @property
    def snapshot_path(self) -> Path:
        return self.dir / "snapshot.json"

    def ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
