"""Price estimation endpoints — Modules 14 & 34."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.v1.jurisdiction import FactOut
from app.core.disclaimers import PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS
from app.services import cities
from app.services import valuation as svc

router = APIRouter()


class ValuationRequest(BaseModel):
    city: str = Field("bengaluru", description="bengaluru | chennai")
    sqft: float = Field(..., gt=100, le=100_000)
    rooms: int = Field(..., ge=1, le=20)
    bath: float | None = Field(None, ge=0, le=20)
    balcony: float | None = Field(None, ge=0, le=10)
    area_type: str = "Super built-up  Area"
    corporation: str | None = Field(
        None, description="North | South | East | West | Central"
    )
    ready_to_move: bool = True
    locality: str | None = Field(
        None, description="Locality name — used for guidance value and "
                          "transaction-price lookup, which are keyed by locality"
    )


class ValuationResponse(BaseModel):
    data: dict[str, FactOut]
    explanation: list[dict[str, Any]]
    model: dict[str, Any]
    confidence: dict[str, Any]
    disclaimers: list[str]


@router.post("/estimate", response_model=ValuationResponse)
async def estimate(req: ValuationRequest) -> ValuationResponse:
    """Estimate an asking price band.

    Returns a range, never a single number.

    Guidance value is returned only if someone recorded it by hand from the
    official portal; transaction price only where the city's dataset is
    genuinely recorded sales. Otherwise both come back UNAVAILABLE with the
    reason and a route to obtain them.
    """
    city = cities.get(req.city)
    inp = svc.ValuationInput(
        sqft=req.sqft,
        rooms=req.rooms,
        bath=req.bath,
        balcony=req.balcony,
        area_type=req.area_type,
        corporation=req.corporation,
        ready_to_move=req.ready_to_move,
        locality=req.locality,
    )
    facts = svc.estimate(inp, city=city.id)
    rep = svc.report(facts)
    metrics = svc._metrics(city.id)

    algo = metrics.get("algorithm") or metrics.get("model", "")
    shipped = (
        metrics.get("model_comparison", {}).get(algo)
        or metrics.get("results_by_feature_set", {})
        .get("without_locality", {})
        .get(algo, {})
    )

    return ValuationResponse(
        data={k: FactOut.of(v) for k, v in facts.items()},
        explanation=svc.explain(inp),
        model={
            "city": city.id,
            "algorithm": algo,
            "target": metrics.get("target"),
            "trained_at": metrics.get("trained_at"),
            "training_rows": metrics.get("dataset", {}).get("rows_clean", metrics.get("n_rows")),
            "spatial_blocks": metrics.get("dataset", {}).get("spatial_blocks", metrics.get("n_blocks")),
            "ward_match_rate": metrics.get("gis", {}).get("ward_match_rate", metrics.get("ward_match_rate")),
            "spatial_cv_r2": shipped.get("spatial_cv", {}).get("r2"),
            "random_cv_r2": shipped.get("random_cv", {}).get("r2"),
            "leakage_gap_r2": shipped.get("leakage_gap_r2"),
            "spatial_cv_mae_inr_per_sqft": shipped.get("spatial_cv", {}).get("mae"),
            "test_split_warning": metrics.get("test_split_warning"),
            "interval": metrics.get("conformal"),
            "selection_basis": (
                "Selected on spatial-block cross-validation, not random k-fold. "
                "Random k-fold leaks neighbouring properties between folds."
            ),
            "model_card": "docs/model-cards/price-model.md",
        },
        confidence={
            "overall": rep.overall,
            "note": (
                "Capped at 0.45 regardless of validation score: the training "
                "data is asking prices from a dataset of uncertain vintage."
            ),
        },
        disclaimers=[PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    )
