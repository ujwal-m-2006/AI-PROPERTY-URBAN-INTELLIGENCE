"""Phase 7 — development feasibility rules engine (Modules 6 & 18).

A deterministic, cited, versioned interpreter of development-control rules. Not
machine learning: statutory limits are not something to predict.

Three properties matter more than coverage:

  1. A rule cannot fire unless it carries a clause reference. Regulation without
     a citation is folklore.
  2. UNVERIFIED rules never fire in production. They are reported in a
     `pending_verification` list so the gap is visible rather than silent.
  3. A missing input yields UNAVAILABLE plus a `blocking_unknowns` entry — never
     a default, an average or a typical value.

Consequence today: FAR is unverified, so the engine returns UNAVAILABLE for FAR
and everything downstream of it, and tells you exactly what to go and find. That
is the correct output for the current state of the evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.facts import Category, Fact, Method, SourceRef, Status, Tier, build_report

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"

FLOOR_TO_FLOOR_M = 3.0

# Confidence attaching to a road width by how it was established. This is the
# dominant term in feasibility confidence, because FAR, height and setbacks are
# all functions of road width.
ROAD_WIDTH_CONFIDENCE = {
    "sanctioned_plan": 0.90,
    "official_document": 0.85,
    "survey": 0.85,
    "dataset": 0.60,
    "measured": 0.55,
    "estimated": 0.35,
}


@dataclass(slots=True)
class FeasibilityInput:
    plot_area_sqm: float | None = None
    road_width_m: float | None = None
    road_width_source: str = "estimated"
    land_use: str | None = None
    building_type: str = "residential"
    plot_frontage_m: float | None = None
    corner_plot: bool = False


@dataclass(slots=True)
class FeasibilityResult:
    facts: dict[str, Fact[Any]] = field(default_factory=dict)
    blocking_unknowns: list[str] = field(default_factory=list)
    pending_verification: list[dict[str, str]] = field(default_factory=list)
    ruleset_version: str = "unknown"


def _ruleset() -> dict[str, Any]:
    """Load the ruleset.

    Parsed with PyYAML when available; falls back to a tiny reader for the
    fields the engine actually needs, so the demo runs on a bare interpreter.
    """
    path = RULES_DIR / "rmp2015" / "zoning.yaml"
    if not path.exists():
        return {}

    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        return _minimal_parse(path.read_text(encoding="utf-8"))


def _minimal_parse(text: str) -> dict[str, Any]:
    """Extract rule ids, statuses and clause refs without a YAML dependency."""
    rules: list[dict[str, Any]] = []
    version = "unknown"
    current: dict[str, Any] | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("version:") and version == "unknown":
            version = line.split(":", 1)[1].strip()
        if line.startswith("- id:"):
            current = {"id": line.split(":", 1)[1].strip(), "status": "UNVERIFIED"}
            rules.append(current)
        elif current is not None and line.startswith("status:"):
            current["status"] = line.split(":", 1)[1].strip()
        elif current is not None and line.startswith("clause:"):
            value = line.split(":", 1)[1].strip()
            current["clause"] = None if value in ("null", "~", "") else value
        elif current is not None and line.startswith("description:"):
            current["description"] = line.split(":", 1)[1].strip().strip('"')
        elif current is not None and line.startswith("blocking_task:"):
            current["blocking_task"] = line.split(":", 1)[1].strip()

    return {"ruleset": {"version": version, "rules": rules}}


def _can_fire(rule: dict[str, Any]) -> bool:
    """A rule fires only if it is VERIFIED and carries a clause reference."""
    return rule.get("status") == "VERIFIED" and bool(rule.get("clause"))


def _rule_source() -> SourceRef:
    from uuid import NAMESPACE_URL, uuid5

    url = (
        "https://www.indiacode.nic.in/ViewFileUploaded?path=AC_KA_71_402_00001_11_"
        "1552283484255%2Frulesindividualfile%2F&file=zoning_regulations_rmp2015f.pdf"
    )
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, url),
        name="Zoning Regulations, Revised Master Plan 2015 (Bengaluru)",
        organisation="Bangalore Development Authority",
        source_url=url,
        tier=Tier.T1,
        source_updated=date(2007, 6, 25),
        licence="Government publication",
    )


def evaluate(inp: FeasibilityInput) -> FeasibilityResult:
    data = _ruleset().get("ruleset", {})
    rules: list[dict[str, Any]] = data.get("rules", [])
    result = FeasibilityResult(ruleset_version=str(data.get("version", "unknown")))

    result.pending_verification = [
        {
            "rule": r["id"],
            "description": r.get("description", ""),
            "status": r.get("status", "UNVERIFIED"),
            "blocked_by": r.get("blocking_task", ""),
            "reason": (
                "No clause reference recorded"
                if not r.get("clause")
                else "Not yet verified against the source document"
            ),
        }
        for r in rules
        if not _can_fire(r)
    ]

    # --- inputs, as facts ------------------------------------------------

    if inp.plot_area_sqm is None or inp.plot_area_sqm <= 0:
        result.facts["plot_area"] = Fact.unavailable("Plot area not supplied")
        result.blocking_unknowns.append("plot area")
    else:
        result.facts["plot_area"] = Fact.observed(
            round(inp.plot_area_sqm, 2),
            source=SourceRef(
                source_id=_rule_source().source_id,
                name="User-supplied plot area",
                tier=Tier.T4,
            ),
            confidence=0.55,
            unit="sq.m",
            status=Status.INDICATIVE,
            caveats=["Plot area as entered by the user; not surveyed"],
        )

    if inp.road_width_m is None or inp.road_width_m <= 0:
        result.facts["road_width"] = Fact.unavailable(
            "Abutting road width not supplied. FAR, height and setbacks are all "
            "functions of road width, so nothing downstream can be computed."
        )
        result.blocking_unknowns.append("abutting road width")
    else:
        conf = ROAD_WIDTH_CONFIDENCE.get(inp.road_width_source, 0.35)
        result.facts["road_width"] = Fact.observed(
            round(inp.road_width_m, 2),
            source=SourceRef(
                source_id=_rule_source().source_id,
                name=f"Road width ({inp.road_width_source.replace('_', ' ')})",
                tier=Tier.T4 if inp.road_width_source == "estimated" else Tier.T3,
                source_url=None,
            ),
            confidence=min(conf, 0.70),
            unit="m",
            status=Status.INDICATIVE,
            caveats=[
                f"Road width established by: {inp.road_width_source}. "
                "BBMP Road History is portal-only and the open road-width dataset "
                "covers major roads only (audit 2.4)."
            ],
        )

    if not inp.land_use:
        result.facts["land_use"] = Fact.unavailable(
            "Land use not supplied. Notified land use is not available as a "
            "machine-readable layer (audit finding 4)."
        )
        result.blocking_unknowns.append("notified land use")
    else:
        result.facts["land_use"] = Fact.observed(
            inp.land_use,
            source=SourceRef(
                source_id=_rule_source().source_id,
                name="User-declared land use",
                tier=Tier.T4,
            ),
            confidence=0.45,
            status=Status.INDICATIVE,
            caveats=["Declared by the user; not confirmed against a notified plan"],
        )

    # --- regulatory outputs ----------------------------------------------

    far_rule = next(
        (r for r in rules if r["id"] == "far-by-road-width-residential"), None
    )
    if far_rule and _can_fire(far_rule):
        # Populated once the FAR table is transcribed and cited.
        result.facts["far"] = Fact.unavailable("FAR table not yet transcribed")
    else:
        result.facts["far"] = Fact.unavailable(
            "Applicable FAR is not established. The governing instruments are "
            "now identified — the Zonal Regulations to RMP-2015 notified as UDD "
            "235 MNJ 2025 on 05.01.2026, and the per-corporation Building "
            "(Amendment) Bye-laws 2026 effective 14.05.2026 (audit R2, R3 "
            "closed) — but their FAR clauses have not been transcribed into this "
            "engine. Publishing a FAR figure from a document located but not "
            "read would be a guess wearing a citation, with financial "
            "consequences."
        )
        result.blocking_unknowns.append("verified FAR clause for this zone")

    height_rule = next((r for r in rules if r["id"] == "height-cap-narrow-road"), None)
    if (
        height_rule
        and _can_fire(height_rule)
        and inp.road_width_m is not None
        and inp.road_width_m < 9.0
    ):
        result.facts["max_height"] = Fact.derive(
            15.0,
            inputs=[result.facts["road_width"]],
            method=Method.RULE_EVALUATION,
            assumptions=[
                f"Road width {inp.road_width_m} m, established by "
                f"{inp.road_width_source}",
                "Height cap includes stilt floor",
            ],
            unit="m",
            rule_ids=[height_rule["id"]],
        )
    else:
        result.facts["max_height"] = Fact.unavailable(
            "Maximum permissible height is not established. The applicable height "
            "rules are unverified against the source document (audit R2)."
        )
        result.blocking_unknowns.append("verified height rule")

    # --- arithmetic, which fires whenever its inputs exist ----------------

    far = result.facts["far"]
    area = result.facts["plot_area"]
    if far.is_known and area.is_known:
        result.facts["max_built_up"] = Fact.derive(
            round(float(area.value) * float(far.value), 2),
            inputs=[area, far],
            method=Method.RULE_EVALUATION,
            assumptions=["Maximum built-up area = plot area x FAR"],
            unit="sq.m",
        )
    else:
        result.facts["max_built_up"] = Fact.unavailable(
            "Depends on FAR and plot area; at least one is unavailable"
        )

    height = result.facts["max_height"]
    if height.is_known:
        result.facts["potential_floors"] = Fact.derive(
            math.floor(float(height.value) / FLOOR_TO_FLOOR_M),
            inputs=[height],
            method=Method.RULE_EVALUATION,
            assumptions=[
                f"Floor-to-floor height assumed at {FLOOR_TO_FLOOR_M} m; the "
                "actual figure depends on the design",
                "Indicative count only; not a sanctioned floor configuration",
            ],
        )
    else:
        result.facts["potential_floors"] = Fact.unavailable(
            "Depends on maximum permissible height, which is unavailable"
        )

    for key in ("setbacks", "ground_coverage", "parking_spaces", "potential_units"):
        result.facts[key] = Fact.unavailable(
            "Not computed: the governing rule is unverified against the source "
            "document (audit R2)"
        )

    return result


def confidence_report(result: FeasibilityResult):
    return build_report(
        {Category.PLANNING: result.facts},
        blocking_unknowns=sorted(set(result.blocking_unknowns)),
    )
