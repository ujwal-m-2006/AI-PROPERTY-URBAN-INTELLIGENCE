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

    # --- declared regulatory parameters -------------------------------------
    # The platform cannot establish these: the governing notification is a scan
    # and no clause has been transcribed. A user who HAS them (sanctioned plan,
    # authority confirmation, the published regulations) may supply them, and
    # everything downstream then computes with its assumptions on show.
    #
    # Every one carries a source flag, and the confidence of anything derived
    # from it is bounded by that flag. A figure declared as `estimated` produces
    # a visibly weaker answer than one from an `official_document`.
    far: float | None = None
    far_source: str = "estimated"
    max_height_m: float | None = None
    max_height_source: str = "estimated"
    ground_coverage_pct: float | None = None
    setback_front_m: float | None = None
    setback_rear_m: float | None = None
    setback_side_m: float | None = None
    parking_per_unit: float | None = None
    avg_unit_size_sqm: float | None = None


@dataclass(slots=True)
class FeasibilityResult:
    facts: dict[str, Fact[Any]] = field(default_factory=dict)
    blocking_unknowns: list[str] = field(default_factory=list)
    pending_verification: list[dict[str, str]] = field(default_factory=list)
    # Values the CALLER supplied rather than the engine establishing them. A
    # distinct list from pending_verification: "this rule is unverified" and
    # "you told me this number" are different admissions.
    user_declared: list[str] = field(default_factory=list)
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
    if inp.far is not None and inp.far > 0:
        # Declared, not established. Status stays ESTIMATED and the source flag
        # caps the confidence, so nothing downstream can look authoritative.
        conf = min(ROAD_WIDTH_CONFIDENCE.get(inp.far_source, 0.35), 0.70)
        result.facts["far"] = Fact.observed(
            round(float(inp.far), 3),
            source=SourceRef(
                source_id=_rule_source().source_id,
                name=f"FAR declared by user ({inp.far_source.replace('_', ' ')})",
                tier=Tier.T4 if inp.far_source == "estimated" else Tier.T3,
                source_url=None,
            ),
            confidence=conf,
            status=Status.ESTIMATED,
            caveats=[
                f"FAR DECLARED BY YOU, established by: {inp.far_source}. This "
                "platform has not verified it against the zoning regulations — "
                "the governing notification (UDD 235 MNJ 2025) is a scanned "
                "document and no clause has been transcribed.",
                "Everything computed from this figure inherits its uncertainty. "
                "Confirm with the planning authority before relying on any of it.",
            ],
        )
        result.user_declared.append("FAR is user-declared and unverified against the gazette")
    elif far_rule and _can_fire(far_rule):
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
            "consequences. If you hold the applicable FAR — from a sanctioned "
            "plan, the planning authority, or the published regulations — supply "
            "it as `far` with a `far_source`, and every dependent value will be "
            "computed with its assumptions shown."
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
    elif inp.max_height_m is not None and inp.max_height_m > 0:
        conf = min(ROAD_WIDTH_CONFIDENCE.get(inp.max_height_source, 0.35), 0.70)
        result.facts["max_height"] = Fact.observed(
            round(float(inp.max_height_m), 2),
            source=SourceRef(
                source_id=_rule_source().source_id,
                name=f"Height declared by user "
                     f"({inp.max_height_source.replace('_', ' ')})",
                tier=Tier.T4 if inp.max_height_source == "estimated" else Tier.T3,
                source_url=None,
            ),
            confidence=conf,
            unit="m",
            status=Status.ESTIMATED,
            caveats=[
                f"HEIGHT DECLARED BY YOU, established by: "
                f"{inp.max_height_source}. Not verified against the building "
                "bye-laws, which are issued per city corporation and are not "
                "transcribed here.",
            ],
        )
        result.user_declared.append("Maximum height is user-declared and unverified")
    else:
        result.facts["max_height"] = Fact.unavailable(
            "Maximum permissible height is not established. The applicable height "
            "rules are unverified against the source document (audit R2). Supply "
            "`max_height_m` with a source if you hold it."
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

    # --- setbacks and ground coverage -------------------------------------
    declared_setbacks = {
        "front_m": inp.setback_front_m,
        "rear_m": inp.setback_rear_m,
        "side_m": inp.setback_side_m,
    }
    if any(v is not None and v >= 0 for v in declared_setbacks.values()):
        supplied = {k: round(float(v), 2)
                    for k, v in declared_setbacks.items() if v is not None}
        result.facts["setbacks"] = Fact.derive(
            supplied,
            inputs=[area] if area.is_known else [],
            method=Method.RULE_EVALUATION,
            assumptions=[
                "Setbacks as declared by you, not read from the zoning "
                "regulations",
                "A setback schedule depends on plot dimensions, abutting road "
                "width and building category; confirm the applicable one",
            ],
            unit="m",
        )
        result.user_declared.append("Setbacks are user-declared")
    else:
        result.facts["setbacks"] = Fact.unavailable(
            "Not computed: the setback schedule is unverified against the source "
            "document (audit R2). Supply setback_front_m / _rear_m / _side_m to "
            "compute the buildable footprint from your own figures."
        )

    if inp.ground_coverage_pct is not None and 0 < inp.ground_coverage_pct <= 100:
        pct = float(inp.ground_coverage_pct)
        footprint = (round(float(area.value) * pct / 100.0, 2)
                     if area.is_known else None)
        result.facts["ground_coverage"] = Fact.derive(
            {"percent": round(pct, 2), "footprint_sqm": footprint},
            inputs=[area] if area.is_known else [],
            method=Method.RULE_EVALUATION,
            assumptions=[
                "Ground coverage percentage as declared by you",
                "Footprint = plot area x coverage percentage",
            ],
        )
        result.user_declared.append("Ground coverage is user-declared")
    else:
        result.facts["ground_coverage"] = Fact.unavailable(
            "Not computed: the permissible coverage is unverified (audit R2). "
            "Supply ground_coverage_pct to compute the footprint."
        )

    # --- units, then parking, which depends on them -----------------------
    built_up = result.facts["max_built_up"]
    if built_up.is_known and inp.avg_unit_size_sqm and inp.avg_unit_size_sqm > 0:
        units = int(float(built_up.value) // float(inp.avg_unit_size_sqm))
        result.facts["potential_units"] = Fact.derive(
            units,
            inputs=[built_up],
            method=Method.RULE_EVALUATION,
            assumptions=[
                f"Average unit size assumed at {inp.avg_unit_size_sqm} sq.m as "
                "declared",
                "Ignores common areas, circulation, stilts and services, so the "
                "real figure will be lower",
                "An indicative count, not an approved unit configuration",
            ],
        )
    else:
        result.facts["potential_units"] = Fact.unavailable(
            "Depends on maximum built-up area and an average unit size. "
            "Supply avg_unit_size_sqm once FAR is available."
        )

    units_fact = result.facts["potential_units"]
    if units_fact.is_known and inp.parking_per_unit and inp.parking_per_unit > 0:
        result.facts["parking_spaces"] = Fact.derive(
            math.ceil(int(units_fact.value) * float(inp.parking_per_unit)),
            inputs=[units_fact],
            method=Method.RULE_EVALUATION,
            assumptions=[
                f"Parking ratio of {inp.parking_per_unit} space(s) per unit as "
                "declared, not read from the bye-laws",
                "Ignores visitor parking and any category-specific minimum",
            ],
        )
        result.user_declared.append("Parking ratio is user-declared")
    else:
        result.facts["parking_spaces"] = Fact.unavailable(
            "Depends on the unit count and a parking ratio. Supply "
            "parking_per_unit, and avg_unit_size_sqm for the unit count."
        )

    return result


def confidence_report(result: FeasibilityResult):
    return build_report(
        {Category.PLANNING: result.facts},
        blocking_unknowns=sorted(set(result.blocking_unknowns)),
    )
