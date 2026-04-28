from pathlib import Path

import pytest

from xteam_lib.errors import SnapshotCorrupt
from xteam_lib.session import Session, new_session_id
from xteam_lib.snapshot import Snapshot, load_snapshot, save_snapshot


def test_roundtrip(tmp_xteam_root: Path):
    session = Session(new_session_id(), root=tmp_xteam_root)
    snap = Snapshot(
        session_id=session.id,
        phase="P2",
        prd_path="/tmp/prd.md",
        kb_snapshot={"source": "fixture", "modules": {}},
        drafts={"v0": "hello"},
        must_answer_state={"schema": {"applicable": True, "status": "missing"}},
        open_questions_for_human=[],
        human_responses=[],
    )
    save_snapshot(session, snap)

    loaded = load_snapshot(session)
    assert loaded.phase == "P2"
    assert loaded.drafts["v0"] == "hello"
    assert loaded.must_answer_state["schema"]["applicable"] is True


def test_load_missing_file_raises(tmp_xteam_root: Path):
    session = Session(new_session_id(), root=tmp_xteam_root)
    with pytest.raises(FileNotFoundError):
        load_snapshot(session)


def test_corrupt_json_raises_snapshot_corrupt(tmp_xteam_root: Path):
    session = Session(new_session_id(), root=tmp_xteam_root)
    session.ensure_dir()
    session.snapshot_path.write_text("{ not valid json")
    with pytest.raises(SnapshotCorrupt):
        load_snapshot(session)
