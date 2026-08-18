"""Nearby facilities endpoint — Modules 9, 10 and 11."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.v1.jurisdiction import FactOut
from app.core.disclaimers import PLATFORM_NATURE
from app.core.problems import OutsideCoverage
from app.services import jurisdiction as jur
from app.services import proximity as svc

router = APIRouter()


@router.get("", summary="Nearby transport, government offices and services")
async def nearby(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(5000, ge=100, le=20000),
    city: str = Query("bengaluru", description="bengaluru | chennai"),
) -> dict[str, Any]:
    """Nearest facilities by category, with derived accessibility scores.

    Government offices are returned with an explicit warning that proximity is
    not jurisdiction.
    """
    if not jur.in_coverage(lng, lat, city):
        raise OutsideCoverage(
            f"This point lies outside the {city} coverage area.", city=city
        )

    result = svc.facts(lat, lng, radius_m, city_id=city)

    groups: dict[str, Any] = {}
    for group, categories in svc.GROUPS.items():
        items = []
        for cat in categories:
            for place in result["found"].get(cat, []):
                items.append(
                    {
                        "name": place.name,
                        "name_kn": place.name_kn,
                        "category": cat,
                        "distance_m": place.distance_m,
                        "lat": place.lat,
                        "lng": place.lng,
                        "is_government": place.is_government,
                    }
                )
        groups[group] = sorted(items, key=lambda i: i["distance_m"])

    report = result["confidence"]

    return {
        "available": result["available"],
        "query": {"lat": lat, "lng": lng, "radius_m": radius_m, "city": city},
        "groups": groups,
        "scores": {k: FactOut.of(v) for k, v in result["scores"].items()},
        "confidence": {
            "overall": report.overall,
            "note": (
                "Community-sourced (OpenStreetMap, tier T3) — capped at 0.70. "
                "Distances are straight-line, not road distance."
            ),
        },
        "caveats": {
            "government": svc.GOV_JURISDICTION_CAVEAT,
            "coverage": (
                "Absence of a facility here is not evidence that none exists. "
                "OpenStreetMap completeness varies across Greater Bengaluru."
            ),
        },
        "attribution": "© OpenStreetMap contributors (ODbL 1.0)",
        "disclaimers": [PLATFORM_NATURE],
    }
