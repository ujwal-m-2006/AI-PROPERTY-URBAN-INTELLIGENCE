"""Module 12 — reported flooding locations.

Proximity to reported flooding, and nothing more. See `app/services/flood.py`
for why this is not a risk score: the source has no return period, depth or
drainage data, so a score would be invented rather than computed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.core.disclaimers import PLATFORM_NATURE
from app.services import cities, flood

router = APIRouter()


@router.get("", summary="Reported flooding locations near a point")
async def nearby_flooding(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    city: str = Query("bengaluru"),
    radius_m: float = Query(flood.SEARCH_RADIUS_M, ge=100, le=10_000),
) -> dict[str, Any]:
    c = cities.get(city)

    if not flood.is_available(c.id):
        return {
            "city": {"id": c.id, "name": c.name},
            "available": False,
            "reason": (
                f"No flooding-location layer has been ingested for {c.name}. "
                "The BBMP dataset covers Bengaluru only."
            ),
            "not_a_finding": (
                "This is not a finding that the location does not flood."
            ),
        }

    hits = flood.nearby(lng, lat, radius_m=radius_m)
    return {
        "city": {"id": c.id, "name": c.name},
        "available": True,
        "reported_locations": hits,
        "count_within_radius": len(flood.nearby(lng, lat, radius_m=radius_m,
                                                limit=10_000)),
        "radius_m": radius_m,
        "nearest_m": hits[0]["distance_m"] if hits else None,
        "is_a_risk_score": False,
        "why_not_a_score": flood.NOT_A_SCORE,
        "absence_note": flood.ABSENCE_NOTE,
        "excluded_from_risk_score": (
            "The environmental risk score continues to list flood as excluded. "
            "This layer is reported separately and is never folded into it."
        ),
        "disclaimers": [PLATFORM_NATURE, flood.NOT_A_SCORE],
    }


@router.get("/coverage", summary="What the flooding layer holds")
async def coverage(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    if not flood.is_available(c.id):
        return {"city": {"id": c.id, "name": c.name}, "available": False,
                "reason": f"No flooding-location layer for {c.name}."}
    cov = flood.coverage()
    cov["city"] = {"id": c.id, "name": c.name}
    return cov
