"""Module 12 — reported flooding locations near a point.

This module answers exactly one question: *has flooding been reported near
here, and how near?*

It deliberately does not answer "what is the flood risk", because the data
cannot. The BBMP layers are reported locations with no return period, no depth,
no drainage capacity and no terrain. Converting them into a 0-100 score would
manufacture a hazard model out of a list of addresses.

So `analytics.risk_score` continues to list flood among its exclusions, and
this module returns a separate, clearly-bounded fact. The two must not be
merged — a test asserts flood stays excluded from the score.

THE ASYMMETRY THAT MATTERS
--------------------------
A nearby point is weak evidence that flooding has occurred nearby. No nearby
point is **not** evidence that it hasn't — the dataset is a report, not a
survey. That asymmetry is stated in every response rather than left for the
reader to infer.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.facts import Fact, SourceRef, Status, Tier

DATA = Path(__file__).resolve().parents[3] / "data" / "processed"
LAYER = "flood_locations_bengaluru.geojson"
META = "source_flood_locations_bengaluru.json"

# Beyond this a reported point tells you nothing useful about a specific plot.
SEARCH_RADIUS_M = 2000.0

NOT_A_SCORE = (
    "This is a proximity observation, not a flood risk score. The source is a "
    "list of reported flooding locations with no return period, depth, "
    "drainage or terrain data. It cannot support a risk percentage and none is "
    "produced."
)

ABSENCE_NOTE = (
    "No reported location nearby is NOT evidence that this property does not "
    "flood. It means none was recorded in this dataset, which is a report "
    "rather than a survey."
)


@lru_cache(maxsize=2)
def _load(path_str: str, mtime: float) -> list[tuple[float, float, dict]]:
    payload = json.loads(Path(path_str).read_text(encoding="utf-8"))
    return [(f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1],
             f["properties"])
            for f in payload.get("features", [])
            if f.get("geometry", {}).get("type") == "Point"]


def _points() -> list[tuple[float, float, dict]]:
    path = DATA / LAYER
    if not path.exists():
        return []
    return _load(str(path), path.stat().st_mtime)


def is_available(city_id: str = "bengaluru") -> bool:
    return city_id == "bengaluru" and bool(_points())


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def nearby(lng: float, lat: float, radius_m: float = SEARCH_RADIUS_M,
           limit: int = 5) -> list[dict[str, Any]]:
    """Reported flooding locations within the radius, nearest first."""
    out = []
    # ~0.02 deg is comfortably beyond 2 km; prefilter before the exact distance.
    span = radius_m / 111_000.0 * 1.6
    for lon, la, props in _points():
        if abs(lon - lng) > span or abs(la - lat) > span:
            continue
        d = _haversine_m(lng, lat, lon, la)
        if d <= radius_m:
            out.append({
                "distance_m": round(d, 1),
                "name": props.get("name"),
                "kind": props.get("kind"),
                "lng": lon, "lat": la,
            })
    out.sort(key=lambda r: r["distance_m"])
    return out[:limit]


@lru_cache(maxsize=1)
def coverage() -> dict[str, Any]:
    meta_path = DATA / META
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    pts = _points()
    kinds: dict[str, int] = {}
    for _lon, _lat, p in pts:
        k = p.get("kind") or "unknown"
        kinds[k] = kinds.get(k, 0) + 1
    return {
        "available": bool(pts),
        "points": len(pts),
        "kinds": kinds,
        "search_radius_m": SEARCH_RADIUS_M,
        "is_a_risk_score": False,
        "why_not": NOT_A_SCORE,
        "absence_note": ABSENCE_NOTE,
        "caveats": meta.get("caveats", []),
        "source_url": meta.get("source_url"),
        "licence": meta.get("licence"),
        "tier": "T2",
    }


@lru_cache(maxsize=1)
def _source() -> SourceRef:
    meta_path = DATA / META
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, meta.get("source_url", "flood-locations")),
        name=meta.get("name", "Reported flooding locations"),
        organisation=meta.get("organisation", "BBMP"),
        source_url=meta.get("source_url"),
        tier=Tier.T2,
        retrieved_at=(datetime.fromisoformat(meta["retrieved_at"])
                      if meta.get("retrieved_at") else None),
        licence=meta.get("licence"),
    )


def facts(lng: float, lat: float, city_id: str = "bengaluru") -> dict[str, Fact[Any]]:
    """Nearest reported flooding location, as a Fact."""
    keys = ("nearest_reported_flooding_m", "reported_flooding_within_2km")

    if city_id != "bengaluru":
        reason = ("No flooding-location layer has been ingested for this city. "
                  "The BBMP dataset covers Bengaluru only.")
        return {k: Fact.unavailable(reason) for k in keys}

    if not is_available():
        reason = ("Flood location layer not ingested. Run "
                  "etl/flows/ingest_flood_locations.py.")
        return {k: Fact.unavailable(reason) for k in keys}

    hits = nearby(lng, lat)
    src = _source()

    if not hits:
        note = (f"No flooding location reported within "
                f"{SEARCH_RADIUS_M / 1000:.0f} km. {ABSENCE_NOTE}")
        return {
            "nearest_reported_flooding_m": Fact.unavailable(note),
            "reported_flooding_within_2km": Fact.observed(
                0, source=src, confidence=0.60, status=Status.INDICATIVE,
                caveats=[ABSENCE_NOTE, NOT_A_SCORE],
            ),
        }

    nearest = hits[0]
    return {
        "nearest_reported_flooding_m": Fact.observed(
            nearest["distance_m"], source=src, confidence=0.65,
            status=Status.INDICATIVE, unit="m",
            caveats=[
                f"Nearest reported location: {nearest.get('kind')}"
                + (f" — {nearest['name']}" if nearest.get("name") else ""),
                NOT_A_SCORE,
                "A reported point marks a location, not the extent of "
                "flooding around it.",
            ],
        ),
        "reported_flooding_within_2km": Fact.observed(
            len(nearby(lng, lat, limit=10_000)), source=src, confidence=0.65,
            status=Status.INDICATIVE,
            caveats=[NOT_A_SCORE, ABSENCE_NOTE],
        ),
    }
