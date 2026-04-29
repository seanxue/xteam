"""Session snapshot read/write.

Single JSON file per session. Schema lives in
schemas/xteam/snapshot.schema.json (added in a later task when the
full field set stabilizes). For M1 we roundtrip without schema
validation — validation is added when more phases write to the same
file.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from xteam_lib.errors import SnapshotCorrupt
from xteam_lib.session import Session


@dataclass
class Snapshot:
    session_id: str
    phase: str
    prd_path: str
    kb_snapshot: dict[str, Any]
    drafts: dict[str, str] = field(default_factory=dict)
    rounds: dict[str, dict[str, Any]] = field(default_factory=dict)
    must_answer_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    open_questions_for_human: list[str] = field(default_factory=list)
    human_responses: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    updated_at: str = ""


def save_snapshot(session: Session, snap: Snapshot) -> None:
    session.ensure_dir()
    snap.updated_at = (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    session.snapshot_path.write_text(json.dumps(asdict(snap), indent=2, ensure_ascii=False))


def load_snapshot(session: Session) -> Snapshot:
    path = session.snapshot_path
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise SnapshotCorrupt(f"invalid JSON in {path}: {e}") from e
    return Snapshot(**data)
