"""Jurisdiction endpoints — Module 1."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.disclaimers import STANDARD_SET
from app.core.problems import OutsideCoverage
from app.facts import Fact
from app.services import jurisdiction as svc

router = APIRouter()


class FactOut(BaseModel):
    """Wire format for a Fact. Provenance travels with the value, always."""

    value: Any | None
    status: str
    tier: str
    confidence: float
    colour: str
    # A bare 12 next to "road width" is ambiguous. Units travel with the value.
    unit: str | None = None
    source: dict[str, Any] | None = None
    reason: str | None = None
    assumptions: list[str] = []
    caveats: list[str] = []

    @classmethod
    def of(cls, fact: Fact[Any]) -> FactOut:
        return cls(
            value=fact.value,
            status=str(fact.status),
            tier=str(fact.tier),
            confidence=fact.confidence,
            colour=fact.colour,
            unit=fact.unit,
            source=(
                {
                    "name": fact.source.name,
                    "organisation": fact.source.organisation,
                    "url": fact.source.source_url,
                    "tier": str(fact.source.tier),
                    "licence": fact.source.licence,
                    "retrieved_at": (
                        fact.source.retrieved_at.isoformat()
                        if fact.source.retrieved_at
                        else None
                    ),
                    "source_updated": (
                        fact.source.source_updated.isoformat()
                        if fact.source.source_updated
                        else None
                    ),
                }
                if fact.source
                else None
            ),
            reason=fact.reason,
            assumptions=fact.assumptions,
            caveats=fact.caveats,
        )


class JurisdictionResponse(BaseModel):
    found: bool
    query: dict[str, Any]
    data: dict[str, FactOut]
    confidence: dict[str, Any]
    disclaimers: list[str] = list(STANDARD_SET)


@router.get("/wards", summary="All wards for a city with a representative point")
async def wards(city: str = Query("bengaluru")) -> dict[str, Any]:
    """Backs search and the ward picker.

    The platform must be usable without the map — if WebGL is unavailable, a
    user still needs a way to choose a location.
    """
    data = svc.list_wards(city)
    return {"city": city, "count": len(data), "data": data}


@router.get("", response_model=JurisdictionResponse, summary="Jurisdiction for a point")
async def get_jurisdiction(
    lat: float = Query(..., ge=-90, le=90, description="Latitude (WGS84)"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude (WGS84)"),
    city: str = Query("bengaluru", description="bengaluru | chennai"),
) -> JurisdictionResponse:
    """Which corporation, zone, ward and administrative units contain this point.

    Fields we do not hold are returned as UNAVAILABLE with the reason, not
    omitted and never blank-filled.
    """
    if not svc.in_coverage(lng, lat, city):
        raise OutsideCoverage(
            f"This point lies outside the {city} coverage area.",
            city=city,
            coverage_bbox=list(svc.CITY_BBOX.get(city, svc.GBA_BBOX)),
        )

    result = svc.jurisdiction(lng, lat, city)
    report = result.confidence

    return JurisdictionResponse(
        found=result.found,
        query={"lat": lat, "lng": lng, "city": city},
        data={k: FactOut.of(v) for k, v in result.facts.items()},
        confidence={
            "overall": report.overall,
            "weakest_category": str(report.weakest) if report.weakest else None,
            "blocking_unknowns": report.blocking_unknowns,
            "note": (
                "Overall confidence is the minimum across categories, not the "
                "mean — a section with no data must not be averaged away."
            ),
        },
    )


@router.get("/coverage", summary="Which jurisdiction fields are available where")
async def coverage(city: str = Query("bengaluru")) -> dict[str, Any]:
    """Two layers answer different questions. This says which covers what.

    Added because "is taluk available everywhere?" and "is survey number
    available everywhere?" have different answers, and a single coverage figure
    would blur them.
    """
    from app.services import admin_boundaries, cities, revenue

    c = cities.get(city)
    admin = admin_boundaries.coverage(c.id)

    out: dict[str, Any] = {
        "city": {"id": c.id, "name": c.name},
        "administrative_layer": {
            "fields": ["district", "taluk"],
            "areal_coverage": "COMPLETE within the city bounding box",
            "available": admin["available"],
            "districts": admin["districts"],
            "taluk_count": admin["taluk_count"],
            "taluks": admin["taluks"],
            "tier": "T3",
            "status": "INDICATIVE",
            "why_indicative": admin_boundaries.CAVEAT,
        },
    }

    if c.id == "bengaluru" and revenue.is_available():
        rev = revenue.coverage()
        out["cadastral_layer"] = {
            "fields": ["hobli", "village", "survey_number",
                       "district and taluk at higher confidence"],
            "areal_coverage": "PARTIAL — published revenue sheets only",
            "available": True,
            "taluks": rev["taluks"],
            "hoblis": rev["hoblis"],
            "village_count": rev["village_count"],
            "parcel_count": rev["parcel_count"],
            "tier": "T2",
            "status": "VERIFIED (survey number INDICATIVE)",
            "note": rev["note"],
        }
    else:
        out["cadastral_layer"] = {
            "fields": ["hobli", "village", "survey_number"],
            "areal_coverage": "NONE",
            "available": False,
            "reason": (
                f"No cadastral revenue-sheet layer has been ingested for "
                f"{c.name}. Hobli, village and survey number are unavailable "
                "there, and a boundary layer cannot supply them."
            ),
        }

    out["read_this_first"] = (
        "District and taluk resolve for every point in the city. Hobli, village "
        "and survey number resolve only inside published revenue sheets — those "
        "are cadastral records, not administrative boundaries, and no polygon "
        "layer can produce them."
    )
    return out
