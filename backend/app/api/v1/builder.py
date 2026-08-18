"""BUILDER MODE endpoint — development project ROI (Module 19)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.disclaimers import (
    FEASIBILITY_IS_NOT_APPROVAL,
    PLATFORM_NATURE,
    PREDICTIONS_ARE_NOT_FACTS,
)
from app.services import builder as svc
from app.services import cities
from app.services import valuation as val

router = APIRouter()


class BuilderRequest(BaseModel):
    city: str = Field("bengaluru")
    land_area_sqft: float = Field(..., gt=0, le=10_000_000)
    land_cost_total: float = Field(..., ge=0)
    land_cost_per_sqft: float | None = Field(
        None, gt=0, description="Alternative to land_cost_total")
    construction_cost_per_sqft: float = Field(2200, gt=0, le=100_000)
    expected_builtup_sqft: float = Field(..., gt=0, le=10_000_000)
    num_units: int = Field(..., ge=1, le=10_000)
    avg_unit_size_sqft: float = Field(..., gt=0, le=100_000)

    expected_selling_price_psf: float | None = Field(
        None, gt=0, le=200_000,
        description="Omit to use the trained ML price model for this city",
    )
    corporation: str | None = None

    other_costs_pct: float = Field(8.0, ge=0, le=60)
    marketing_pct: float = Field(3.0, ge=0, le=30)
    finance_rate_pct: float = Field(11.0, ge=0, le=40)
    project_months: int = Field(30, ge=1, le=180)
    debt_share_pct: float = Field(60.0, ge=0, le=100)


@router.post("/analyze", summary="BUILDER MODE — project cost, revenue and ROI")
async def analyze(req: BuilderRequest) -> dict[str, Any]:
    city = cities.get(req.city)

    land_total = (
        req.land_cost_per_sqft * req.land_area_sqft
        if req.land_cost_per_sqft else req.land_cost_total
    )

    price = req.expected_selling_price_psf
    source = "user-supplied"
    ml_note = None

    if price is None:
        est = val.estimate(
            val.ValuationInput(
                sqft=req.avg_unit_size_sqft,
                rooms=max(1, int(req.avg_unit_size_sqft // 550)),
                bath=None,
                corporation=req.corporation,
            ),
            city=city.id,
        )
        predicted = est["price_per_sqft"].value
        if predicted is None:
            return {
                "error": "No selling price supplied and no trained model available",
                "detail": est["price_per_sqft"].reason,
            }
        price = float(predicted)
        source = f"ML PREDICTION ({city.name} price model)"
        ml_note = est["price_per_sqft"].caveats[0]

    result = svc.analyse(
        svc.BuilderInput(
            land_area_sqft=req.land_area_sqft,
            land_cost_total=land_total,
            construction_cost_per_sqft=req.construction_cost_per_sqft,
            expected_builtup_sqft=req.expected_builtup_sqft,
            num_units=req.num_units,
            avg_unit_size_sqft=req.avg_unit_size_sqft,
            expected_selling_price_psf=price,
            other_costs_pct=req.other_costs_pct,
            marketing_pct=req.marketing_pct,
            finance_rate_pct=req.finance_rate_pct,
            project_months=req.project_months,
            debt_share_pct=req.debt_share_pct,
        ),
        price_source=source,
    )

    result["city"] = {"id": city.id, "name": city.name}
    if ml_note:
        result["ml_price_caveat"] = ml_note
    result["regulatory_note"] = (
        "This model says nothing about what may lawfully be built. FAR, height "
        "and setback limits are unverified — see Development feasibility."
    )
    result["disclaimers"] = [
        PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS, FEASIBILITY_IS_NOT_APPROVAL,
    ]
    return result
