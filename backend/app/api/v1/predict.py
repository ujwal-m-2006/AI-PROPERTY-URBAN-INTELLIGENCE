"""Prediction strategy endpoints — single / dual / multi model, plus glossary."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.core.disclaimers import PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS
from app.services import cities, ensemble, glossary
from app.services import valuation as val

router = APIRouter()


class PredictRequest(BaseModel):
    city: str = Field("bengaluru", description="bengaluru | chennai")
    mode: Literal["single", "dual", "multi"] = "single"
    sqft: float = Field(..., gt=100, le=100_000)
    rooms: int = Field(..., ge=1, le=20)
    bath: float | None = Field(None, ge=0, le=20)
    balcony: float | None = Field(None, ge=0, le=10)
    area_type: str = "Super built-up  Area"
    corporation: str | None = None
    compare_modes: bool = False


def _row(req: PredictRequest, city_id: str):
    bundle = val._bundle(city_id)
    if bundle is None:
        return None
    inp = val.ValuationInput(
        sqft=req.sqft, rooms=req.rooms, bath=req.bath, balcony=req.balcony,
        area_type=req.area_type, corporation=req.corporation,
    )
    return val._feature_row(inp, bundle, city_id)


@router.post("", summary="Predict using single, dual or multi-model strategy")
async def predict(req: PredictRequest) -> dict[str, Any]:
    city = cities.get(req.city)
    row = _row(req, city.id)
    if row is None:
        return {
            "available": False,
            "reason": f"No trained model for {city.name}.",
        }

    result = ensemble.predict(city.id, row, req.mode)
    if result.get("available") and result.get("prediction"):
        result["estimated_total_value"] = round(result["prediction"] * req.sqft)

    payload: dict[str, Any] = {
        "city": {"id": city.id, "name": city.name},
        "input": req.model_dump(exclude={"city", "compare_modes"}),
        "result": result,
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }
    if req.compare_modes:
        payload["all_modes"] = ensemble.compare_modes(city.id, row)
    return payload


@router.get("/models", summary="Models trained and saved for a city")
async def models(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    cat = ensemble._catalogue(c.id)
    if not cat:
        return {"city": c.id, "available": False,
                "reason": "No trained models for this city yet."}

    return {
        "city": {"id": c.id, "name": c.name},
        "available": True,
        "count": len(cat["ranked"]),
        "selected_for_single_mode": cat["ranked"][0] if cat["ranked"] else None,
        "target_label": cat.get("target_label"),
        "models": [
            {
                "rank": i + 1,
                "algorithm": name,
                "used_in": (
                    ["single", "dual", "multi"] if i == 0
                    else ["dual", "multi"] if i == 1
                    else ["multi"]
                ),
                **cat["detail"].get(name, {}),
            }
            for i, name in enumerate(cat["ranked"])
        ],
        "modes": ensemble.MODE_INFO,
        "ranking_basis": (
            "Ranked by spatial-block cross-validation R2 — the score that "
            "measures generalisation to unseen localities."
        ),
    }


@router.get("/glossary", summary="Terms, conversions and where ML is used")
async def terms() -> dict[str, Any]:
    return glossary.payload()
