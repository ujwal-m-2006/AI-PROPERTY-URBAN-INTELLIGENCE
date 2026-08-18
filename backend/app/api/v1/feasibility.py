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


class FeasibilityResponse(BaseModel):
    data: dict[str, FactOut]
    blocking_unknowns: list[str]
    pending_verification: list[dict[str, str]]
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
        )
    )
    report = engine.confidence_report(result)

    return FeasibilityResponse(
        data={k: FactOut.of(v) for k, v in result.facts.items()},
        blocking_unknowns=report.blocking_unknowns,
        pending_verification=result.pending_verification,
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
