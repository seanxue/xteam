"""KB diff generation from roundtable results.

Extracts candidate updates for permanent KB writeback (P7).
v1 supports 3 types: new_adr, new_pitfall, update_convention.
Spec §4.4.
"""
from __future__ import annotations

from typing import Any


def extract_kb_diff_candidates(
    session_id: str,
    merge_changelogs: list[list[dict[str, Any]]],
    human_responses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a kb-diff payload from roundtable merge changelogs and human responses.

    Each significant merge action becomes a candidate update.
    Human responses from P3.5/P5 become new_adr or new_pitfall entries.
    """
    candidates: list[dict[str, Any]] = []
    source_prefix = f"xteam-session/{session_id}"

    for round_idx, changelog in enumerate(merge_changelogs, 1):
        for entry in changelog:
            action = entry.get("action", "")
            if action in ("fixed", "conflict_resolved"):
                candidates.append({
                    "type": "new_adr",
                    "scope": f"roundtable/round_{round_idx}",
                    "summary": entry["summary"],
                    "rationale": f"Round {round_idx} {entry['source_role']} reviewer {entry['severity']} issue -> architect {action}",
                    "source": source_prefix,
                })
            elif action == "accepted_risk":
                candidates.append({
                    "type": "new_pitfall",
                    "scope": f"roundtable/round_{round_idx}",
                    "summary": f"Accepted risk: {entry['summary']}",
                    "rationale": f"Round {round_idx} {entry['source_role']} reviewer identified, architect accepted with stated reason",
                    "source": source_prefix,
                })

    for resp in human_responses:
        content = resp.get("content", "")
        phase = resp.get("source_phase", "unknown")
        if content:
            candidates.append({
                "type": "new_adr",
                "scope": "human_decision",
                "summary": content,
                "rationale": f"Human decision during {phase}",
                "source": source_prefix,
            })

    return {
        "session_id": session_id,
        "candidate_updates": candidates,
    }
