"""End-to-end smoke test covering the Python side of M1 only.

The architect subagent dispatch happens in the skill (Markdown +
Agent tool), which we can't exercise in unit tests. This file tests
that every deterministic step the skill invokes works in sequence.
"""
from pathlib import Path

from xteam_lib.kb import load_kb_from_fixtures
from xteam_lib.must_answer import compute_applicability, load_canonical_items
from xteam_lib.prd import parse_prd, validate_prd
from xteam_lib.session import Session, new_session_id
from xteam_lib.snapshot import Snapshot, save_snapshot, load_snapshot


def test_p0_p1_pipeline_runs_for_valid_prd(
    fixtures_dir: Path, tmp_xteam_root: Path
):
    # Phase 0
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    validate_prd(prd)

    # Phase 1a: applicability
    state = compute_applicability(prd, load_canonical_items())
    applicable = {k for k, v in state.items() if v.applicable}
    assert "schema" in applicable
    assert "compat_and_isolation" in applicable
    assert "hotspot" in applicable

    # Phase 1b: KB
    module_names = [m["name"] for m in prd.frontmatter["involved_modules"]]
    snap = load_kb_from_fixtures(module_names, fixtures_dir / "kb")
    assert set(snap.modules.keys()) == set(module_names)

    # Phase 1c: snapshot
    session = Session(new_session_id(), root=tmp_xteam_root)
    ss = Snapshot(
        session_id=session.id,
        phase="P1-complete",
        prd_path=str(prd.source_path),
        kb_snapshot=snap.to_dict(),
        must_answer_state={
            k: {"applicable": v.applicable, "status": v.status}
            for k, v in state.items()
        },
    )
    save_snapshot(session, ss)

    # Reload and verify integrity
    loaded = load_snapshot(session)
    assert loaded.phase == "P1-complete"
    assert loaded.must_answer_state["compat_and_isolation"]["applicable"] is True
    assert "comment" in loaded.kb_snapshot["modules"]
