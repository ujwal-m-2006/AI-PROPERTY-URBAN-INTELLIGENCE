"""BUYER MODE and INVESTOR MODE endpoints (Modules 19 and 20)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.disclaimers import (
    KHATA_IS_NOT_TITLE,
    PLATFORM_NATURE,
    PREDICTIONS_ARE_NOT_FACTS,
)
from app.services import advisory, analytics, cities, proximity
from app.services import valuation as val

router = APIRouter()


class PropertyInput(BaseModel):
    label: str = Field("Property", max_length=60)
    city: str = "bengaluru"
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    sqft: float = Field(..., gt=100, le=100_000)
    rooms: int = Field(..., ge=1, le=20)
    bath: float | None = Field(None, ge=0, le=20)
    asking_price_per_sqft: float | None = Field(None, gt=0, le=200_000)
    corporation: str | None = None


class CompareRequest(BaseModel):
    options: list[PropertyInput] = Field(..., min_length=2, max_length=4)


def _evaluate(p: PropertyInput) -> dict[str, Any]:
    """Run the shared pipeline for one property."""
    city = cities.get(p.city)

    est = val.estimate(
        val.ValuationInput(sqft=p.sqft, rooms=p.rooms, bath=p.bath,
                           corporation=p.corporation),
        city=city.id,
    )
    predicted = est["price_per_sqft"].value
    half = None
    if est["price_range_high"].value is not None and predicted is not None:
        half = float(est["price_range_high"].value) - float(predicted)

    scores: dict[str, Any] = {}
    prox: dict[str, Any] = {}
    if p.lat is not None and p.lng is not None:
        result = proximity.facts(p.lat, p.lng, city_id=city.id)
        if result["available"]:
            prox = result["found"]
            scores = {k: f.value for k, f in result["scores"].items()}

    def nearest(cat: str) -> float | None:
        places = prox.get(cat) or []
        return float(places[0].distance_m) if places else None

    amenity_1km = sum(
        1 for places in prox.values() for x in places if x.distance_m <= 1000
    ) if prox else None

    demand = analytics.demand_score(
        connectivity_score=scores.get("connectivity_score"),
        healthcare_score=scores.get("healthcare_score"),
        education_score=scores.get("education_score"),
        amenity_count_1km=amenity_1km,
        locality_listing_count=None, max_listing_count=None,
    )
    risk = analytics.risk_score(
        lake_distance_m=nearest("lake"),
        park_distance_m=nearest("park"),
        hospital_distance_m=nearest("hospital"),
        fire_station_distance_m=nearest("fire_station"),
        connectivity_score=scores.get("connectivity_score"),
    )

    return {
        "label": p.label,
        "city": city.id,
        "city_name": city.name,
        "predicted_psf": predicted,
        "interval_half": half,
        "observed_psf": p.asking_price_per_sqft,
        "demand": demand,
        "risk": risk,
        "connectivity": scores.get("connectivity_score"),
        "scores": scores,
        "target_label": analytics.city_target_label(city.id),
    }


@router.post("/buyer", summary="BUYER MODE — is this property worth considering?")
async def buyer(p: PropertyInput) -> dict[str, Any]:
    e = _evaluate(p)
    verdict = advisory.buyer_verdict(
        observed_psf=e["observed_psf"],
        predicted_psf=e["predicted_psf"],
        interval_half=e["interval_half"],
        demand=e["demand"],
        risk=e["risk"],
        connectivity=e["connectivity"],
        records_verified=False,   # never true: no government record is fetchable
    )
    return {
        "city": {"id": e["city"], "name": e["city_name"]},
        "input": p.model_dump(exclude={"city"}),
        "verdict": verdict,
        "price": {
            "asking_psf": e["observed_psf"],
            "model_estimate_psf": e["predicted_psf"],
            "interval_half_width": e["interval_half"],
            "target_label": e["target_label"],
            "estimated_total": (
                round(e["predicted_psf"] * p.sqft) if e["predicted_psf"] else None
            ),
        },
        "demand": e["demand"],
        "risk": e["risk"],
        "accessibility": e["scores"],
        "records": {
            "status": "MANUAL VERIFICATION REQUIRED",
            "checked": [],
            "note": (
                "Khata / e-Khata, property tax, building approval, occupancy "
                "certificate and encumbrance status are not available through "
                "any public API. None has been checked."
            ),
            "khata_note": KHATA_IS_NOT_TITLE,
        },
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }


@router.post("/investor", summary="INVESTOR MODE — compare and rank options")
async def investor(req: CompareRequest) -> dict[str, Any]:
    evaluated = [_evaluate(p) for p in req.options]
    ranking = advisory.rank_options(evaluated)
    return {
        "compared": len(evaluated),
        "ranking": ranking,
        "detail": [
            {
                "label": e["label"],
                "city": e["city_name"],
                "predicted_psf": e["predicted_psf"],
                "observed_psf": e["observed_psf"],
                "demand": e["demand"]["band"],
                "risk": e["risk"]["band"],
                "connectivity": e["connectivity"],
                "target_label": e["target_label"],
            }
            for e in evaluated
        ],
        "records_note": (
            "No option has had its official records verified — none is "
            "machine-readable. Ranking reflects price, demand, connectivity and "
            "proximity risk only."
        ),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }
