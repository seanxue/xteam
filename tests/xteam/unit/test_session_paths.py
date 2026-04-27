from pathlib import Path

import pytest

from xteam_lib.session import Session, new_session_id


def test_new_session_id_is_unique_uuid_shape():
    a = new_session_id()
    b = new_session_id()
    assert a != b
    assert len(a) == 36
    assert a.count("-") == 4


def test_session_paths_are_under_xteam_root(tmp_xteam_root: Path):
    sid = new_session_id()
    session = Session(sid, root=tmp_xteam_root)
    assert session.dir == tmp_xteam_root / sid
    assert session.snapshot_path == tmp_xteam_root / sid / "snapshot.json"


def test_session_dir_is_created_lazily(tmp_xteam_root: Path):
    sid = new_session_id()
    session = Session(sid, root=tmp_xteam_root)
    assert not session.dir.exists()
    session.ensure_dir()
    assert session.dir.is_dir()


def test_session_rejects_traversal_in_id(tmp_xteam_root: Path):
    with pytest.raises(ValueError, match="invalid session id"):
        Session("../evil", root=tmp_xteam_root)
