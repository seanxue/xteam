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
    source: str  # "fixture" | "mcp" | "fixture+temp"
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    temp_layer: list[dict[str, Any]] = field(default_factory=list)

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


def merge_temp_layer(
    snap: KBSnapshot, human_responses: list[dict[str, Any]]
) -> KBSnapshot:
    """Overlay P3.5 human responses onto a KB snapshot.

    Returns a new KBSnapshot with temp_layer set. The original
    snapshot's modules are not mutated. The temp_layer is session-only
    and never written to permanent KB (that's P7's job). Spec §4.1.
    """
    if not human_responses:
        return KBSnapshot(
            fetched_at=snap.fetched_at,
            source=snap.source,
            modules=dict(snap.modules),
            temp_layer=[],
        )
    return KBSnapshot(
        fetched_at=snap.fetched_at,
        source=f"{snap.source}+temp",
        modules=dict(snap.modules),
        temp_layer=list(human_responses),
    )


# --- Role slicing ---
#
# Canonical slicing rules (spec §4.3). The table is data, not code,
# so new roles / fields only require editing _SLICE_RULES below.

_SLICE_RULES: dict[str, dict[str, Any]] = {
    "architect": {"all": True},
    "data": {
        "module_profile_keys": ["tech_stack", "data_stores"],
        "pitfall_categories": ["schema", "migration"],
        "convention_keys": ["data"],
        "adr_categories": ["data"],
        "keep_incidents_categories": [],
    },
    "perf": {
        "module_profile_keys": ["tech_stack", "capacity"],
        "pitfall_categories": ["hotspot", "cache"],
        "convention_keys": [],
        "adr_categories": [],
        "keep_incidents_categories": ["performance"],
    },
    "security": {
        "module_profile_keys": ["tech_stack"],
        "pitfall_categories": ["auth", "data_leak"],
        "convention_keys": ["security"],
        "adr_categories": ["security"],
        "keep_incidents_categories": [],
    },
    "qa": {
        "module_profile_keys": ["tech_stack", "test_strategy"],
        "pitfall_categories": [],
        "convention_keys": ["testing"],
        "adr_categories": [],
        "keep_incidents_categories": ["regression"],
    },
}


def slice_for_role(snap: KBSnapshot, role: str) -> dict[str, dict[str, Any]]:
    if role not in _SLICE_RULES:
        raise ValueError(f"unknown role: {role!r}")
    rules = _SLICE_RULES[role]
    if rules.get("all"):
        return snap.modules

    result: dict[str, dict[str, Any]] = {}
    for mod_name, mod_data in snap.modules.items():
        result[mod_name] = _slice_module(mod_data, rules)
    return result


def _slice_module(mod: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    # module_profile: keep whitelisted keys only
    profile = mod.get("module_profile", {})
    kept_profile = {k: v for k, v in profile.items() if k in rules["module_profile_keys"]}
    if kept_profile:
        out["module_profile"] = kept_profile
    # historical_pitfalls: filter by category
    pfs = [
        p
        for p in mod.get("historical_pitfalls", [])
        if set(p.get("categories", [])) & set(rules["pitfall_categories"])
    ]
    if pfs:
        out["historical_pitfalls"] = pfs
    # conventions: keep whitelisted subkeys
    convs = mod.get("conventions", {}) or {}
    kept_convs = {k: v for k, v in convs.items() if k in rules["convention_keys"]}
    if kept_convs:
        out["conventions"] = kept_convs
    # relevant_adrs: filter by category
    adrs = [
        a
        for a in mod.get("relevant_adrs", [])
        if set(a.get("categories", [])) & set(rules["adr_categories"])
    ]
    if adrs:
        out["relevant_adrs"] = adrs
    # recent_incidents: filter by category
    incs = [
        i
        for i in mod.get("recent_incidents", [])
        if set(i.get("categories", [])) & set(rules["keep_incidents_categories"])
    ]
    if incs:
        out["recent_incidents"] = incs
    return out
