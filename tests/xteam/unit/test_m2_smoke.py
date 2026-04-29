"""M2 deterministic pipeline smoke test.

Tests the Python side of M2: reviewer output loading, midcheck eval,
must-answer merging, KB temp layer, kb-diff generation, snapshot with
rounds. Does NOT test LLM dispatch (that lives in SKILL.md).
"""
import json
from pathlib import Path

from xteam_lib.kb import load_kb_from_fixtures, merge_temp_layer, slice_for_role
from xteam_lib.kb_diff import extract_kb_diff_candidates
from xteam_lib.must_answer import compute_applicability, load_canonical_items
from xteam_lib.prd import parse_prd, validate_prd
from xteam_lib.roundtable import evaluate_midcheck, merge_must_answer_updates, collect_all_questions
from xteam_lib.schema_validate import validate_against
from xteam_lib.session import Session, new_session_id
from xteam_lib.snapshot import Snapshot, save_snapshot, load_snapshot


def test_m2_full_pipeline(fixtures_dir: Path, tmp_xteam_root: Path):
    # Phase 0: parse + validate
    prd = parse_prd(fixtures_dir / "prd" / "valid-minimal.md")
    validate_prd(prd)

    # Phase 1: applicability + KB
    state = compute_applicability(prd, load_canonical_items())
    must_answer = {k: {"applicable": v.applicable, "status": v.status} for k, v in state.items()}
    module_names = [m["name"] for m in prd.frontmatter["involved_modules"]]
    kb_snap = load_kb_from_fixtures(module_names, fixtures_dir / "kb")

    # Phase 2 would dispatch architect — simulate v0
    v0_draft = "## 方案概述\ntest draft content" + "x" * 100

    # Phase 3: load fixture reviewer outputs
    reviewer_outputs = []
    for name in ["data-round1-changes-requested", "perf-round1-approved",
                  "security-round1-block", "qa-round1-changes-requested"]:
        with open(fixtures_dir / "reviewer" / f"{name}.json") as f:
            ro = json.load(f)
        validate_against(ro, "reviewer-output")
        reviewer_outputs.append(ro)

    # Simulate merge output
    merge_output = {
        "mode": "merge",
        "tech_design_markdown": v0_draft + "\n## Updated sections",
        "must_answer_updates": [{"id": "schema", "status": "draft"}],
        "merge_changelog": [
            {"action": "fixed", "source_role": "data", "severity": "critical",
             "summary": "Added unique index on rec_candidates" + " " * 20},
            {"action": "escalated", "source_role": "security", "severity": "critical",
             "summary": "Auth requirement needs business decision" + " " * 20},
        ],
        "open_questions_for_human": ["需确认推荐理由是否属于PII"],
        "unresolvable_conflicts": [],
    }

    # Merge must-answer updates
    all_updates = [ro["must_answer_updates"] for ro in reviewer_outputs]
    all_updates.append(merge_output["must_answer_updates"])
    updated_state = merge_must_answer_updates(must_answer, all_updates)

    # Phase 3.5: midcheck
    midcheck = evaluate_midcheck(reviewer_outputs, merge_output, updated_state)
    # With 4 reviewer questions + 1 merge question >= 5, plus 1 escalated critical
    assert midcheck.triggered is True
    assert len(midcheck.signals) >= 1

    # Simulate human responses
    human_responses = [{"content": "推荐理由不属于PII,无需脱敏", "source_phase": "P3.5"}]
    merged_kb = merge_temp_layer(kb_snap, human_responses)
    assert "temp" in merged_kb.source

    # KB slicing still works on merged snapshot
    data_slice = slice_for_role(merged_kb, "data")
    assert "comment" in data_slice

    # Phase 4/5 would repeat — skip to P6 output

    # KB diff generation
    kb_diff = extract_kb_diff_candidates(
        session_id="test-m2",
        merge_changelogs=[merge_output["merge_changelog"]],
        human_responses=human_responses,
    )
    validate_against(kb_diff, "kb-diff")
    assert len(kb_diff["candidate_updates"]) >= 2  # fixed + human

    # Snapshot with rounds
    session = Session(new_session_id(), root=tmp_xteam_root)
    snap = Snapshot(
        session_id=session.id,
        phase="P6-complete",
        prd_path=str(prd.source_path),
        kb_snapshot=kb_snap.to_dict(),
        drafts={"v0": v0_draft, "v1": merge_output["tech_design_markdown"]},
        rounds={
            "round_1": {
                "reviewer_outputs": reviewer_outputs,
                "merge_changelog": merge_output["merge_changelog"],
                "absent_reviewers": [],
            },
        },
        must_answer_state=updated_state,
        human_responses=human_responses,
    )
    save_snapshot(session, snap)

    # Reload and verify
    loaded = load_snapshot(session)
    assert loaded.phase == "P6-complete"
    assert len(loaded.rounds["round_1"]["reviewer_outputs"]) == 4
    assert loaded.human_responses[0]["content"] == "推荐理由不属于PII,无需脱敏"
