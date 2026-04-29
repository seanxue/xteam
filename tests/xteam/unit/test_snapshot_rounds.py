"""Test Snapshot with rounds data (M2 extension)."""
from pathlib import Path

from xteam_lib.session import Session, new_session_id
from xteam_lib.snapshot import Snapshot, save_snapshot, load_snapshot


def test_snapshot_with_rounds_roundtrip(tmp_xteam_root: Path):
    session = Session(new_session_id(), root=tmp_xteam_root)
    snap = Snapshot(
        session_id=session.id,
        phase="P3-complete",
        prd_path="/tmp/prd.md",
        kb_snapshot={"source": "fixture", "modules": {}},
        drafts={"v0": "draft0", "v1": "draft1"},
        rounds={
            "round_1": {
                "reviewer_outputs": [
                    {"role": "data", "verdict": "changes_requested"},
                    {"role": "perf", "verdict": "approved"},
                ],
                "merge_changelog": [
                    {"action": "fixed", "source_role": "data", "severity": "critical", "summary": "added index"}
                ],
                "absent_reviewers": ["security"],
            }
        },
        must_answer_state={"schema": {"applicable": True, "status": "draft"}},
    )
    save_snapshot(session, snap)

    loaded = load_snapshot(session)
    assert loaded.phase == "P3-complete"
    assert loaded.rounds["round_1"]["absent_reviewers"] == ["security"]
    assert len(loaded.rounds["round_1"]["reviewer_outputs"]) == 2
    assert loaded.drafts["v1"] == "draft1"


def test_snapshot_without_rounds_still_works(tmp_xteam_root: Path):
    """M1 snapshots have no rounds field — must remain compatible."""
    session = Session(new_session_id(), root=tmp_xteam_root)
    snap = Snapshot(
        session_id=session.id,
        phase="P2-complete",
        prd_path="/tmp/prd.md",
        kb_snapshot={"source": "fixture", "modules": {}},
    )
    save_snapshot(session, snap)
    loaded = load_snapshot(session)
    assert loaded.rounds == {}
