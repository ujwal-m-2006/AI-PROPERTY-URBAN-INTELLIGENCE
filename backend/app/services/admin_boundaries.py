"""District and taluk for any point in either city.

This layer and the revenue-sheet layer answer overlapping questions, and the
precedence between them is the whole design:

    district / taluk   revenue sheet (T2, VERIFIED) where it covers the point,
                       otherwise this boundary layer (T3, INDICATIVE)
    hobli              revenue sheet only — hobli is not an LGD level
    village            revenue sheet only
    survey number      revenue sheet only — a boundary polygon cannot produce one

So this module widens *areal* coverage from 3 taluks to the whole of both
cities, and widens *cadastral* coverage not at all. Those are different
questions and the answer says which one it answered.

Every value here is INDICATIVE, for two reasons that are stated rather than
buried: the boundaries are a community republication of LGD and Survey of India
rather than a fetch from either, and no per-feature vintage is published while
both states have reorganised taluks in recent years.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.facts import Fact, SourceRef, Status, Tier

DATA = Path(__file__).resolve().parents[3] / "data" / "processed"

CAVEAT = (
    "District and taluk from an administrative boundary layer republished from "
    "the Local Government Directory and Survey of India. It is INDICATIVE: the "
    "compilation is not the issuing authority, and no vintage is published per "
    "boundary while both states have reorganised taluks in recent years."
)

NO_SURVEY_FROM_BOUNDARY = (
    "A boundary layer establishes which taluk a point falls in. It cannot "
    "produce a hobli, village or survey number — those come from revenue "
    "sheets, which cover only part of Bengaluru."
)


def _path(city_id: str) -> Path:
    return DATA / f"admin_subdistricts_{city_id}.geojson"


@lru_cache(maxsize=4)
def _load(path_str: str, mtime: float) -> list[tuple[tuple, dict, list]]:
    payload = json.loads(Path(path_str).read_text(encoding="utf-8"))
    out = []
    for f in payload.get("features", []):
        geom = f["geometry"]
        polys = ([geom["coordinates"]] if geom["type"] == "Polygon"
                 else geom["coordinates"])
        xs = [p[0] for poly in polys for ring in poly for p in ring]
        ys = [p[1] for poly in polys for ring in poly for p in ring]
        if not xs:
            continue
        out.append(((min(xs), min(ys), max(xs), max(ys)), f["properties"], polys))
    return out


def _polygons(city_id: str) -> list[tuple[tuple, dict, list]]:
    path = _path(city_id)
    if not path.exists():
        return []
    return _load(str(path), path.stat().st_mtime)


def is_available(city_id: str) -> bool:
    return bool(_polygons(city_id))


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            if lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def locate(lng: float, lat: float, city_id: str) -> dict[str, Any] | None:
    """Which subdistrict polygon contains this point."""
    for (minx, miny, maxx, maxy), props, polys in _polygons(city_id):
        if not (minx <= lng <= maxx and miny <= lat <= maxy):
            continue
        for poly in polys:
            if poly and _in_ring(lng, lat, poly[0]):
                if not any(_in_ring(lng, lat, h) for h in poly[1:]):
                    return props
    return None


@lru_cache(maxsize=4)
def coverage(city_id: str) -> dict[str, Any]:
    meta_path = DATA / f"source_admin_subdistricts_{city_id}.json"
    meta = (json.loads(meta_path.read_text(encoding="utf-8"))
            if meta_path.exists() else {})
    cov = meta.get("coverage", {})
    polys = _polygons(city_id)
    return {
        "available": bool(polys),
        "polygons": len(polys),
        "districts": cov.get("districts", []),
        "taluks": cov.get("taluks", []),
        "taluk_count": len(cov.get("taluks", [])),
        "level": "district and taluk (LGD sub-district)",
        "note": (
            "Areal coverage is complete for the city bounding box — every point "
            "inside a polygon resolves to a district and taluk. This does not "
            "extend hobli, village or survey number, which need revenue sheets."
        ),
        "caveats": meta.get("caveats", []),
        "source_url": meta.get("source_url"),
        "licence": meta.get("licence"),
        "tier": "T3",
    }


@lru_cache(maxsize=4)
def _source(city_id: str) -> SourceRef:
    meta_path = DATA / f"source_admin_subdistricts_{city_id}.json"
    meta = (json.loads(meta_path.read_text(encoding="utf-8"))
            if meta_path.exists() else {})
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, meta.get("source_url", f"admin-{city_id}")),
        name=meta.get("name", "District and taluk boundaries"),
        organisation=meta.get("organisation", "LGD / Survey of India (republished)"),
        source_url=meta.get("source_url"),
        tier=Tier.T3,
        retrieved_at=(datetime.fromisoformat(meta["retrieved_at"])
                      if meta.get("retrieved_at") else None),
        licence=meta.get("licence"),
    )


def facts(lng: float, lat: float, city_id: str) -> dict[str, Fact[Any]]:
    """District and taluk for a point, from the boundary layer."""
    keys = ("district", "taluk")

    if not is_available(city_id):
        reason = ("Administrative boundary layer not ingested. Run "
                  "etl/flows/ingest_admin_boundaries.py.")
        return {k: Fact.unavailable(reason) for k in keys}

    hit = locate(lng, lat, city_id)
    if hit is None:
        return {k: Fact.unavailable(
            "Point falls outside every mapped sub-district polygon for this city."
        ) for k in keys}

    src = _source(city_id)
    out: dict[str, Fact[Any]] = {}
    for key in keys:
        value = hit.get(key)
        out[key] = (
            Fact.observed(value, source=src, confidence=0.70,
                          status=Status.INDICATIVE, caveats=[CAVEAT])
            if value else
            Fact.unavailable(f"No {key} name on the matched boundary polygon")
        )
    return out


def merge(revenue_facts: dict[str, Fact[Any]], lng: float, lat: float,
          city_id: str) -> dict[str, Fact[Any]]:
    """Combine the two layers, revenue sheets winning where they have coverage.

    A revenue sheet is T2 and cadastral; a boundary polygon is T3 and areal. So
    the sheet wins where it covers the point, and the boundary layer fills in
    district and taluk everywhere else — but never hobli, village or survey
    number, which it cannot know.
    """
    merged = dict(revenue_facts)
    boundary = facts(lng, lat, city_id)

    for key in ("district", "taluk"):
        existing = merged.get(key)
        if existing is not None and existing.status is not Status.UNAVAILABLE:
            continue                      # revenue sheet already answered it
        merged[key] = boundary[key]

    # These three are cadastral. If the revenue layer could not supply them, the
    # boundary layer cannot either — say why rather than leaving a bare gap.
    for key in ("hobli", "village", "survey_number"):
        existing = merged.get(key)
        if existing is None or existing.status is Status.UNAVAILABLE:
            prior = existing.reason if existing is not None else None
            merged[key] = Fact.unavailable(
                f"{prior + ' ' if prior else ''}{NO_SURVEY_FROM_BOUNDARY}"
            )

    return merged
