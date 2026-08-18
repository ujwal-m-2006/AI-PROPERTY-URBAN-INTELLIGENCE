"""Phase 5 — proximity intelligence (Modules 9, 10, 11).

Nearest transport, government offices and essential services, with distance and
derived accessibility scores.

Two rules this module must never break:

  1. **Nearest is not jurisdictional.** The nearest sub-registrar office is not
     necessarily the one with jurisdiction over a property. Government results
     carry that caveat on every single row, because acting on the wrong one
     wastes a real person's day.
  2. **Absence is not evidence.** OSM completeness varies. "No hospital found
     within 5 km" means we did not find one, not that none exists.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple
from uuid import NAMESPACE_URL, uuid5

from app.facts import Category, Fact, Method, SourceRef, Status, Tier, build_report

DATA = Path(__file__).resolve().parents[3] / "data" / "processed"

EARTH_R = 6_371_000.0
DEFAULT_RADIUS_M = 5_000

TRANSPORT = ["metro_station", "railway_station", "bus_stop", "bus_station", "airport"]
GOVERNMENT = ["government_office", "police_station", "fire_station", "post_office",
              "courthouse"]
HEALTH = ["hospital", "clinic", "pharmacy"]
EDUCATION = ["school", "college", "university"]
DAILY = ["bank", "atm", "fuel", "supermarket", "park"]

GROUPS = {
    "transport": TRANSPORT,
    "government": GOVERNMENT,
    "healthcare": HEALTH,
    "education": EDUCATION,
    "daily_life": DAILY,
}

# Distance in metres at which a category stops adding to the connectivity score.
# Chosen from ordinary walking/commuting expectations, stated so they can be
# argued with rather than hidden in a formula.
SCORE_REFERENCE = {
    "bus_stop": 500,
    "metro_station": 2_000,
    "railway_station": 5_000,
    "hospital": 3_000,
    "clinic": 1_500,
    "pharmacy": 1_000,
    "school": 1_500,
    "college": 5_000,
    "bank": 1_500,
    "supermarket": 1_500,
    "park": 1_000,
    "police_station": 3_000,
    "fire_station": 5_000,
}


class Place(NamedTuple):
    name: str | None
    name_kn: str | None
    category: str
    lat: float
    lng: float
    distance_m: int
    is_government: bool


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


@lru_cache(maxsize=2)
def _load(path_str: str, mtime: float) -> list[dict[str, Any]]:
    return json.loads(Path(path_str).read_text(encoding="utf-8")).get("features", [])


CITY_AMENITY_FILE = {
    "bengaluru": "osm_amenities.json",
    "chennai": "osm_amenities_chennai.json",
}


def _features(city_id: str = "bengaluru") -> list[dict[str, Any]]:
    """Load a city's amenity layer, keyed on file mtime.

    Keying the cache on mtime rather than caching outright means running the
    ingest while the server is up picks up the new data instead of serving a
    stale empty list forever.
    """
    path = DATA / CITY_AMENITY_FILE.get(city_id, "osm_amenities.json")
    if not path.exists():
        return []
    return _load(str(path), path.stat().st_mtime)


def is_available(city_id: str = "bengaluru") -> bool:
    return bool(_features(city_id))


@lru_cache(maxsize=1)
def _source() -> SourceRef:
    meta_path = DATA / "source_osm_amenities.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, "osm-overpass-bengaluru"),
        name=meta.get("name", "OpenStreetMap amenities"),
        organisation="OpenStreetMap contributors",
        source_url="https://www.openstreetmap.org/",
        tier=Tier.T3,
        retrieved_at=(
            datetime.fromisoformat(meta["retrieved_at"])
            if meta.get("retrieved_at") else None
        ),
        source_updated=date.today(),
        licence=meta.get("licence", "ODbL 1.0"),
    )


def nearby(
    lat: float, lng: float, *, radius_m: int = DEFAULT_RADIUS_M,
    limit_per_cat: int = 3, city_id: str = "bengaluru",
) -> dict[str, list[Place]]:
    """Nearest facilities per category within the radius."""
    # Cheap bounding-box prefilter before the trig.
    dlat = radius_m / 111_320.0
    dlng = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))

    buckets: dict[str, list[Place]] = {}
    for f in _features(city_id):
        if abs(f["lat"] - lat) > dlat or abs(f["lng"] - lng) > dlng:
            continue
        d = haversine(lat, lng, f["lat"], f["lng"])
        if d > radius_m:
            continue
        buckets.setdefault(f["category"], []).append(
            Place(
                name=f.get("name"),
                name_kn=f.get("name_kn"),
                category=f["category"],
                lat=f["lat"],
                lng=f["lng"],
                distance_m=int(round(d)),
                is_government=bool(f.get("is_government")),
            )
        )

    return {
        cat: sorted(places, key=lambda p: p.distance_m)[:limit_per_cat]
        for cat, places in buckets.items()
    }


def _score_component(distance_m: int | None, reference_m: int) -> float:
    """1.0 at the door, 0.0 at twice the reference distance, linear between."""
    if distance_m is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (distance_m / (2 * reference_m))))


def scores(found: dict[str, list[Place]]) -> dict[str, Fact[Any]]:
    """Connectivity and accessibility scores, as COMPUTED facts."""
    out: dict[str, Fact[Any]] = {}
    src = _source()

    def nearest_distance(cat: str) -> int | None:
        places = found.get(cat)
        return places[0].distance_m if places else None

    definitions = {
        "connectivity_score": (
            ["bus_stop", "metro_station", "railway_station"],
            "Public transport access",
        ),
        "healthcare_score": (["hospital", "clinic", "pharmacy"], "Healthcare access"),
        "education_score": (["school", "college"], "Education access"),
        "daily_life_score": (["bank", "supermarket", "park"], "Daily amenities"),
    }

    for key, (cats, label) in definitions.items():
        parts, assumptions = [], []
        for cat in cats:
            d = nearest_distance(cat)
            ref = SCORE_REFERENCE.get(cat, 2_000)
            parts.append(_score_component(d, ref))
            assumptions.append(
                f"{cat.replace('_', ' ')}: "
                + (f"nearest {d:,} m" if d is not None else "none found in radius")
                + f" (scores 0 at {2 * ref:,} m)"
            )

        value = round(100 * sum(parts) / len(parts))
        basis = Fact.observed(
            value, source=src, confidence=0.70, status=Status.INDICATIVE
        )
        out[key] = Fact.derive(
            value,
            inputs=[basis],
            method=Method.HEURISTIC,
            assumptions=[
                f"{label}: mean of straight-line distance scores",
                "Straight-line distance, not road or walking distance",
                *assumptions,
            ],
            unit="/100",
            caveats=[
                "OpenStreetMap completeness varies across Greater Bengaluru; a "
                "facility absent from this layer may still exist on the ground",
            ],
        )

    return out


def facts(
    lat: float, lng: float, radius_m: int = DEFAULT_RADIUS_M,
    city_id: str = "bengaluru",
) -> dict[str, Any]:
    if not is_available(city_id):
        reason = (
            "OpenStreetMap amenity layer not ingested for this city. Run "
            f"etl/flows/ingest_osm_amenities.py {city_id}."
        )
        empty = {k: Fact.unavailable(reason) for k in
                 ("connectivity_score", "healthcare_score", "education_score",
                  "daily_life_score")}
        return {
            "found": {}, "scores": empty,
            "confidence": build_report({Category.INFRASTRUCTURE: empty}),
            "available": False,
        }

    found = nearby(lat, lng, radius_m=radius_m, city_id=city_id)
    score_facts = scores(found)

    return {
        "found": found,
        "scores": score_facts,
        "confidence": build_report({Category.INFRASTRUCTURE: score_facts}),
        "available": True,
    }


GOV_JURISDICTION_CAVEAT = (
    "These are the nearest offices by straight-line distance. The office with "
    "JURISDICTION over a property is determined by ward, sub-division and "
    "sub-registrar mapping — not by proximity. Confirm before visiting."
)
