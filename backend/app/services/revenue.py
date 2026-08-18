"""Revenue jurisdiction — taluk, hobli, village and survey number.

Backed by the digitised Bengaluru Urban revenue sheets. Fills the fields that
Module 1 has reported UNAVAILABLE since the first audit.

Two properties this module must keep:

  * **Partial coverage is reported as partial.** Only some taluks and hoblis are
    published. A point outside them returns UNAVAILABLE with the coverage
    actually held — never the nearest parcel, which would be a guess.

  * **A survey number here is indicative.** It comes from a digitised revenue
    sheet, not from a survey. Boundaries and title are settled by the
    Sub-Registrar and a licensed surveyor.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.facts import Fact, SourceRef, Status, Tier

DATA = Path(__file__).resolve().parents[3] / "data" / "processed"
PARCELS = "revenue_parcels.geojson"

SURVEY_CAVEAT = (
    "Survey number read from a digitised revenue sheet. It is INDICATIVE only "
    "and is not a legal determination of boundary, extent or title — those are "
    "settled by the Sub-Registrar and a licensed surveyor."
)


@lru_cache(maxsize=2)
def _load(path_str: str, mtime: float) -> list[tuple[tuple, dict, list]]:
    payload = json.loads(Path(path_str).read_text(encoding="utf-8"))
    out = []
    for f in payload.get("features", []):
        geom = f["geometry"]
        polys = ([geom["coordinates"]] if geom["type"] == "Polygon"
                 else geom["coordinates"])
        xs = [p[0] for poly in polys for ring in poly for p in ring]
        ys = [p[1] for poly in polys for ring in poly for p in ring]
        out.append(((min(xs), min(ys), max(xs), max(ys)), f["properties"], polys))
    return out


def _parcels() -> list[tuple[tuple, dict, list]]:
    path = DATA / PARCELS
    if not path.exists():
        return []
    return _load(str(path), path.stat().st_mtime)


def is_available() -> bool:
    return bool(_parcels())


@lru_cache(maxsize=1)
def coverage() -> dict[str, Any]:
    """What the revenue layer actually covers — stated, not implied."""
    meta_path = DATA / "source_revenue_parcels.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    taluks: dict[str, set] = {}
    villages: set = set()
    for _bbox, pr, _polys in _parcels():
        if pr.get("taluk"):
            taluks.setdefault(pr["taluk"], set()).add(pr.get("hobli"))
        if pr.get("village"):
            villages.add(pr["village"])
    return {
        "available": bool(taluks),
        "district": "Bengaluru Urban",
        "taluks": sorted(taluks),
        "hoblis": sorted({h for hs in taluks.values() for h in hs if h}),
        "village_count": len(villages),
        "parcel_count": len(_parcels()),
        "partial": True,
        "note": (
            "Coverage is partial. Only the taluks and hoblis published in the "
            "source dataset are held; a location outside them returns "
            "UNAVAILABLE rather than a nearest-match guess."
        ),
        "source_url": meta.get("source_url"),
        "licence": meta.get("licence"),
    }


@lru_cache(maxsize=1)
def _source() -> SourceRef:
    meta_path = DATA / "source_revenue_parcels.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, meta.get("source_url", "revenue-parcels")),
        name=meta.get("name", "Bengaluru Urban revenue maps"),
        organisation=meta.get("organisation", "Karnataka Revenue Department"),
        source_url=meta.get("source_url"),
        tier=Tier.T2,
        retrieved_at=(datetime.fromisoformat(meta["retrieved_at"])
                      if meta.get("retrieved_at") else None),
        source_updated=(date.fromisoformat(meta["source_updated"])
                        if meta.get("source_updated") else None),
        licence=meta.get("licence"),
    )


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


def locate(lng: float, lat: float) -> dict[str, Any] | None:
    """Which revenue parcel contains this point, if any."""
    for (minx, miny, maxx, maxy), props, polys in _parcels():
        if not (minx <= lng <= maxx and miny <= lat <= maxy):
            continue
        for poly in polys:
            if poly and _in_ring(lng, lat, poly[0]):
                if not any(_in_ring(lng, lat, h) for h in poly[1:]):
                    return props
    return None


def facts(lng: float, lat: float) -> dict[str, Fact[Any]]:
    """Revenue fields as Facts, ready to merge into the jurisdiction answer."""
    keys = ("district", "taluk", "hobli", "village", "survey_number")

    if not is_available():
        reason = ("Revenue layer not ingested. Run "
                  "etl/flows/ingest_revenue_maps.py.")
        return {k: Fact.unavailable(reason) for k in keys}

    cov = coverage()
    hit = locate(lng, lat)
    if hit is None:
        reason = (
            "Outside the revenue sheets held. Coverage is partial — currently "
            f"{', '.join(cov['taluks'])} taluk(s) only. No nearest-match guess "
            "is made."
        )
        return {k: Fact.unavailable(reason) for k in keys}

    src = _source()
    out: dict[str, Fact[Any]] = {}
    for key in keys:
        value = hit.get(key)
        if value in (None, ""):
            out[key] = Fact.unavailable(f"Field '{key}' empty on the matched parcel")
            continue
        caveats = [SURVEY_CAVEAT] if key == "survey_number" else [
            "From a digitised revenue sheet; coverage is partial and vintage is "
            "not stated per sheet."
        ]
        out[key] = Fact.observed(
            value, source=src, confidence=0.80,
            status=Status.INDICATIVE if key == "survey_number" else Status.VERIFIED,
            caveats=caveats,
        )
    return out
