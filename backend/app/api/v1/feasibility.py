"""Development feasibility endpoint — Modules 6 & 18.

Stateless: a builder can test a hypothetical plot without creating any record.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.v1.jurisdiction import FactOut
from app.core.disclaimers import FEASIBILITY_IS_NOT_APPROVAL, PLATFORM_NATURE
from app.services import instruments
from app.services import rules_engine as engine

router = APIRouter()


class FeasibilityRequest(BaseModel):
    plot_area_sqm: float | None = Field(None, gt=0, le=1_000_000)
    road_width_m: float | None = Field(None, gt=0, le=200)
    road_width_source: Literal[
        "sanctioned_plan", "official_document", "survey", "dataset", "measured", "estimated"
    ] = "estimated"
    land_use: str | None = None
    building_type: str = "residential"
    plot_frontage_m: float | None = Field(None, gt=0, le=10_000)
    corner_plot: bool = False

    # Declared regulatory parameters. The platform cannot establish these; a
    # user who holds them may supply them and everything downstream computes.
    far: float | None = Field(None, gt=0, le=10,
                             description="Floor Area Ratio, if you hold it")
    far_source: str = Field(
        "estimated",
        description="official_document | measured | dataset | estimated")
    max_height_m: float | None = Field(None, gt=0, le=300)
    max_height_source: str = "estimated"
    ground_coverage_pct: float | None = Field(None, gt=0, le=100)
    setback_front_m: float | None = Field(None, ge=0, le=100)
    setback_rear_m: float | None = Field(None, ge=0, le=100)
    setback_side_m: float | None = Field(None, ge=0, le=100)
    parking_per_unit: float | None = Field(None, gt=0, le=10)
    avg_unit_size_sqm: float | None = Field(None, gt=10, le=2000)


class FeasibilityResponse(BaseModel):
    data: dict[str, FactOut]
    blocking_unknowns: list[str]
    pending_verification: list[dict[str, str]]
    # Figures the caller supplied rather than the engine establishing them.
    # Distinct from pending_verification: "this rule is unverified" and "you told
    # me this number" are different admissions and must not be conflated.
    user_declared: list[str] = []
    # True when any output rests on a declared figure. The UI must say so — a
    # computed number that reads as statutory is the failure mode here.
    computed_from_declared: bool = False
    ruleset: dict[str, Any]
    confidence: dict[str, Any]
    disclaimers: list[str]


@router.post("/evaluate", response_model=FeasibilityResponse)
async def evaluate(req: FeasibilityRequest) -> FeasibilityResponse:
    """Evaluate what the development-control rules indicate for a plot.

    Values the rules cannot establish come back UNAVAILABLE with the reason and
    a `blocking_unknowns` entry. They are never defaulted to a typical figure.
    """
    result = engine.evaluate(
        engine.FeasibilityInput(
            plot_area_sqm=req.plot_area_sqm,
            road_width_m=req.road_width_m,
            road_width_source=req.road_width_source,
            land_use=req.land_use,
            building_type=req.building_type,
            plot_frontage_m=req.plot_frontage_m,
            corner_plot=req.corner_plot,
            far=req.far,
            far_source=req.far_source,
            max_height_m=req.max_height_m,
            max_height_source=req.max_height_source,
            ground_coverage_pct=req.ground_coverage_pct,
            setback_front_m=req.setback_front_m,
            setback_rear_m=req.setback_rear_m,
            setback_side_m=req.setback_side_m,
            parking_per_unit=req.parking_per_unit,
            avg_unit_size_sqm=req.avg_unit_size_sqm,
        )
    )
    report = engine.confidence_report(result)

    return FeasibilityResponse(
        data={k: FactOut.of(v) for k, v in result.facts.items()},
        blocking_unknowns=report.blocking_unknowns,
        pending_verification=result.pending_verification,
        user_declared=result.user_declared,
        # True when any output rests on a figure the caller supplied. The UI must
        # say so — a computed number that looks statutory is the failure mode.
        computed_from_declared=bool(result.user_declared),
        ruleset={
            "id": "rmp2015-zoning",
            "version": result.ruleset_version,
            "instrument": "Zoning Regulations, Revised Master Plan 2015 (as amended)",
            "note": (
                "RMP-2031 is draft/withdrawn and is not used. Rules that are not "
                "verified against the source document do not fire."
            ),
            # Located by the Phase 0.5 research pass (audit R2/R3/R4). The
            # engine can now cite what governs the plot while still declining
            # to publish figures it has not transcribed.
            "governing_instruments": instruments.governing_instruments(),
        },
        confidence={
            "overall": report.overall,
            "note": "Bounded by the weakest input — typically the road-width source.",
        },
        disclaimers=[PLATFORM_NATURE, FEASIBILITY_IS_NOT_APPROVAL],
    )
