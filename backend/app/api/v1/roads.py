"""Module 8 — road intelligence.

Nearest mapped road centreline, its hierarchy code and its published widths.

Read `app/services/roads.py` before changing anything here. In particular, no
endpoint in this file may return a field called `road_width`: the source
publishes an existing width and a proposed width that differ by roughly a factor
of two, and collapsing them would silently inflate every feasibility result
derived downstream.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.core.disclaimers import PLATFORM_NATURE
from app.services import cities, roads

router = APIRouter()

NOT_A_SURVEY = (
    "Road width governs FAR, height and setback under the zoning regulations. "
    "The figures here are published map data, not a survey of the road abutting "
    "a specific plot, and they do not establish which road abuts it."
)


@router.get("", summary="Nearest mapped road and its published widths")
async def nearest_road(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    city: str = Query("bengaluru"),
) -> dict[str, Any]:
    c = cities.get(city)

    if c.id != "bengaluru":
        return {
            "city": {"id": c.id, "name": c.name},
            "available": False,
            "reason": (
                f"No road width layer has been ingested for {c.name}. The BBMP "
                "road width map covers Bengaluru only."
            ),
        }

    hit = roads.nearest(lng, lat)
    if hit is None:
        return {
            "city": {"id": c.id, "name": c.name},
            "available": False,
            "reason": (
                f"No mapped road centreline within {roads.MAX_ABUTMENT_M:.0f} m. "
                "This layer is a width map for the roads BBMP tracks, not the "
                "complete street network — most residential lanes are absent."
            ),
            "not_a_finding": (
                "This is not a finding that the location has no road access."
            ),
        }

    return {
        "city": {"id": c.id, "name": c.name},
        "available": True,
        "distance_to_centreline_m": hit["distance_m"],
        "hierarchy_code": hit.get("hierarchy_code"),
        "hierarchy_interpretation_unverified": hit.get(
            "hierarchy_interpretation_unverified"),
        "width_existing_m": hit.get("width_existing_m"),
        "width_proposed_m": hit.get("width_proposed_m"),
        "segment_length_m": hit.get("length_m"),
        "width_caveat": roads.WIDTH_CAVEAT,
        "proposed_width_caveat": roads.PROPOSED_CAVEAT,
        "hierarchy_caveat": roads.HIERARCHY_CAVEAT,
        "abutment_note": (
            "Distance is to the nearest mapped centreline. Whether this road "
            "abuts the property is determined by the property's boundary, which "
            "this platform does not hold."
        ),
        "disclaimers": [PLATFORM_NATURE, NOT_A_SURVEY],
    }


@router.get("/feasibility-input",
            summary="A road width offered for feasibility — never applied automatically")
async def feasibility_input(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    city: str = Query("bengaluru"),
) -> dict[str, Any]:
    """Feasibility requires a user-declared road width with a source flag.

    This offers a candidate carrying the weakest usable flag (`dataset`). It is
    deliberately a separate call from the feasibility evaluation, so that the
    figure can never arrive there without someone choosing it.
    """
    c = cities.get(city)
    out = roads.feasibility_suggestion(lng, lat, city_id=c.id)
    out["city"] = {"id": c.id, "name": c.name}
    out["source_flag_ranking"] = [
        "official_document — from a sanctioned plan (strongest)",
        "measured — surveyed on the ground",
        "dataset — from a published map, such as this one",
        "estimated — declared without evidence (weakest)",
    ]
    out["disclaimers"] = [PLATFORM_NATURE, NOT_A_SURVEY]
    return out


@router.get("/coverage", summary="What the road layer actually covers")
async def coverage(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    if c.id != "bengaluru":
        return {
            "city": {"id": c.id, "name": c.name},
            "available": False,
            "reason": f"No road width layer has been ingested for {c.name}.",
        }
    cov = roads.coverage()
    cov["city"] = {"id": c.id, "name": c.name}
    return cov
