"""Property insights — anomaly, demand, risk, Investment Score, recommendations.

Each block states its own method: ML PREDICTION, DATA-DRIVEN SCORE, or
COMPOSITE. That labelling is deliberate and load-bearing — a weighted formula
is not machine learning and is never presented as such.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.disclaimers import PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS
from app.services import analytics, cities, proximity, recommender
from app.services import valuation as val

router = APIRouter()


class InsightsRequest(BaseModel):
    city: str = Field("bengaluru", description="bengaluru | chennai")
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    sqft: float = Field(..., gt=100, le=100_000)
    rooms: int = Field(..., ge=1, le=20)
    bath: float | None = Field(None, ge=0, le=20)
    observed_price_per_sqft: float | None = Field(None, gt=0, le=200_000)
    corporation: str | None = None


@router.post("/analyze", summary="Full property insight bundle")
async def analyze(req: InsightsRequest) -> dict[str, Any]:
    city = cities.get(req.city)

    # --- ML price prediction -------------------------------------------
    est = val.estimate(
        val.ValuationInput(
            sqft=req.sqft, rooms=req.rooms, bath=req.bath,
            corporation=req.corporation,
        ),
        city=city.id,
    )
    predicted = est["price_per_sqft"].value
    interval_half = None
    if est["price_range_high"].value is not None and predicted is not None:
        interval_half = float(est["price_range_high"].value) - float(predicted)

    # --- proximity (drives the data-driven scores) ----------------------
    prox: dict[str, Any] = {}
    scores: dict[str, Any] = {}
    if req.lat is not None and req.lng is not None:
        result = proximity.facts(req.lat, req.lng, city_id=city.id)
        if result["available"]:
            prox = result["found"]
            scores = {k: f.value for k, f in result["scores"].items()}

    def nearest(category: str) -> float | None:
        places = prox.get(category) or []
        return float(places[0].distance_m) if places else None

    amenity_1km = sum(
        1 for places in prox.values() for p in places if p.distance_m <= 1000
    ) if prox else None

    # --- derived analytics ---------------------------------------------
    demand = analytics.demand_score(
        connectivity_score=scores.get("connectivity_score"),
        healthcare_score=scores.get("healthcare_score"),
        education_score=scores.get("education_score"),
        amenity_count_1km=amenity_1km,
        locality_listing_count=None,
        max_listing_count=None,
    )
    risk = analytics.risk_score(
        lake_distance_m=nearest("lake"),
        park_distance_m=nearest("park"),
        hospital_distance_m=nearest("hospital"),
        fire_station_distance_m=nearest("fire_station"),
        connectivity_score=scores.get("connectivity_score"),
    )
    investment = analytics.investment_score(
        predicted_psf=predicted,
        observed_psf=req.observed_price_per_sqft,
        demand=demand,
        risk=risk,
        connectivity_score=scores.get("connectivity_score"),
    )

    anomaly: dict[str, Any] = {
        "verdict": "UNAVAILABLE",
        "method": analytics.METHOD_ML,
        "reason": "No observed price supplied to compare against the model",
    }
    if req.observed_price_per_sqft and predicted and interval_half:
        anomaly = analytics.price_anomaly(
            req.observed_price_per_sqft, float(predicted), interval_half
        )

    recs = recommender.recommend(
        city.id, sqft=req.sqft, rooms=req.rooms, bath=req.bath,
        price_per_sqft=float(req.observed_price_per_sqft or predicted or 0) or 1.0,
        limit=5,
    )

    return {
        "city": {"id": city.id, "name": city.name},
        "price_prediction": {
            "method": analytics.METHOD_ML,
            "price_per_sqft": predicted,
            "range_low": est["price_range_low"].value,
            "range_high": est["price_range_high"].value,
            "estimated_value": est["estimated_value"].value,
            "target_label": analytics.city_target_label(city.id),
            "caveats": est["price_per_sqft"].caveats,
        },
        "overpricing": anomaly,
        "demand": demand,
        "risk": risk,
        "investment_score": investment,
        "recommendations": recs,
        "accessibility_scores": scores,
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }
