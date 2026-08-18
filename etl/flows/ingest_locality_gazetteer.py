"""Locality gazetteer — the bridge from GIS to ML features.

Neither property dataset carries coordinates; both carry only a locality name
("Whitefield", "Anna Nagar"). Without coordinates, none of the GIS work can
become a model feature.

This flow pulls named place nodes (suburb / neighbourhood / village / town /
quarter / locality) from OpenStreetMap for a city's bounding box, giving a
name -> (lat, lng) lookup. Dataset localities are then fuzzy-matched against it
in ml/features/gis_features.py.

The match is DERIVED (tier T5): a locality name matching an OSM place name is
evidence of location, not proof, and the resolution is locality-level, not
property-level. Every feature built on it inherits that ceiling.

Usage:  python etl/flows/ingest_locality_gazetteer.py [bengaluru|chennai]
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "processed"

OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

CITY_BBOX = {
    "bengaluru": "12.70,77.30,13.25,77.90",
    "chennai": "12.83,80.10,13.25,80.35",
}

PLACE_TYPES = [
    "suburb", "neighbourhood", "quarter", "village", "town",
    "city_district", "locality", "hamlet",
]

USER_AGENT = (
    "GBA-Property-Intelligence/0.1 (academic research prototype; "
    "contact via project README)"
)


def build_query(bbox: str) -> str:
    parts = [f'  node["place"="{p}"]["name"]({bbox});' for p in PLACE_TYPES]
    parts += [f'  way["place"="{p}"]["name"]({bbox});' for p in ("suburb", "neighbourhood")]
    body = "\n".join(parts)
    return f"[out:json][timeout:180];\n(\n{body}\n);\nout center tags;"


def fetch(bbox: str) -> list[dict[str, Any]]:
    query = build_query(bbox)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = httpx.post(
                endpoint, data={"data": query}, headers=headers, timeout=200.0
            )
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except (httpx.HTTPError, ValueError) as exc:
            print(f"  [{endpoint.split('/')[2]}: {type(exc).__name__}]")
            time.sleep(4)
    return []


NOMINATIM = "https://nominatim.openstreetmap.org/search"

CITY_QUERY_SUFFIX = {
    "bengaluru": "Bengaluru, Karnataka, India",
    "chennai": "Chennai, Tamil Nadu, India",
}


def dataset_localities(city: str) -> list[str]:
    """Unique locality names from the city's property dataset."""
    import csv

    files = {
        "bengaluru": ("bengaluru_house_data.csv", "location"),
        "chennai": ("chennai_house_price.csv", "AREA"),
    }
    if city not in files:
        return []
    filename, column = files[city]
    path = ROOT / "data" / "raw" / filename
    if not path.exists():
        return []

    seen: set[str] = set()
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            value = (row.get(column) or "").strip()
            if value:
                seen.add(value)
    return sorted(seen)


def fetch_nominatim(names: list[str], city: str) -> list[dict[str, Any]]:
    """Geocode a small set of locality names one at a time.

    Fallback for when Overpass is rate-limiting. Nominatim's usage policy
    permits low-volume use with an identifying User-Agent and at most one
    request per second — both are honoured here. Only viable because the
    locality count is small; it is never used for bulk geocoding.
    """
    out: list[dict[str, Any]] = []
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    for name in names:
        query = f"{name}, {CITY_QUERY_SUFFIX.get(city, city)}"
        try:
            resp = httpx.get(
                NOMINATIM,
                params={"q": query, "format": "json", "limit": 1},
                headers=headers, timeout=30.0,
            )
            resp.raise_for_status()
            hits = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            print(f"    {name:<24} {type(exc).__name__}")
            time.sleep(1.2)
            continue

        if hits:
            out.append({
                "name": name,
                "name_local": None,
                "place_type": hits[0].get("type"),
                "lat": round(float(hits[0]["lat"]), 6),
                "lng": round(float(hits[0]["lon"]), 6),
            })
            print(f"    {name:<24} {hits[0]['lat']}, {hits[0]['lon']}")
        else:
            print(f"    {name:<24} no match")
        time.sleep(1.2)  # Nominatim policy: max 1 request/second

    return out


def main() -> int:
    city = (sys.argv[1] if len(sys.argv) > 1 else "bengaluru").strip().lower()
    if city not in CITY_BBOX:
        print(f"unknown city {city!r}; choose from {list(CITY_BBOX)}")
        return 1

    print(f"locality gazetteer for {city} (bbox {CITY_BBOX[city]})")
    elements = fetch(CITY_BBOX[city])

    if not elements:
        names = dataset_localities(city)
        print(f"  Overpass unavailable — falling back to Nominatim for "
              f"{len(names)} dataset localities")
        if len(names) > 60:
            print("  too many localities for a polite Nominatim fallback; aborting")
            return 2
        places_list = fetch_nominatim(names, city)
        if not places_list:
            print("  no results from either source")
            return 2
        return _write(city, {p["name"].strip().lower(): p for p in places_list},
                      source="nominatim")

    places: dict[str, dict[str, Any]] = {}
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        if not name:
            continue
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue

        key = name.strip().lower()
        # Prefer the more specific place types when a name appears twice.
        rank = {p: i for i, p in enumerate(PLACE_TYPES)}
        existing = places.get(key)
        this_rank = rank.get(tags.get("place", ""), 99)
        if existing and existing["_rank"] <= this_rank:
            continue

        places[key] = {
            "name": name.strip(),
            "name_local": tags.get("name:kn") or tags.get("name:ta"),
            "place_type": tags.get("place"),
            "lat": round(float(lat), 6),
            "lng": round(float(lon), 6),
            "_rank": this_rank,
        }

    for p in places.values():
        p.pop("_rank", None)

    return _write(city, places, source="overpass")


def _write(city: str, places: dict[str, dict[str, Any]], *, source: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    out_file = OUT / f"locality_gazetteer_{city}.json"
    out_file.write_text(
        json.dumps({"city": city, "source": source,
                    "places": list(places.values())}), encoding="utf-8"
    )

    is_nominatim = source == "nominatim"
    provenance = {
        "name": f"OpenStreetMap locality gazetteer — {city} ({source})",
        "organisation": "OpenStreetMap contributors",
        "source_url": (
            "https://nominatim.openstreetmap.org/" if is_nominatim
            else "https://www.openstreetmap.org/"
        ),
        "tier": "T3",
        "availability": "API",
        "licence": "Open Database License (ODbL) 1.0",
        "attribution": "© OpenStreetMap contributors",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "method": "http_download",
        "transformation": (
            "Nominatim forward geocoding of the dataset's unique locality names, "
            "one request per second per the usage policy"
            if is_nominatim else
            f"Overpass place nodes/ways ({', '.join(PLACE_TYPES)}) within the "
            "city bbox, deduplicated by name preferring the more specific place type"
        ),
        "access_notes": f"{len(places)} unique locality names via {source}",
        "max_confidence": 0.70,
        "verification_status": "COMMUNITY_SOURCED",
        "caveats": [
            "Locality-level resolution only — a locality centroid is not the "
            "property's location",
            "Matching a dataset locality string to a place name is derived "
            "evidence, not proof of location",
        ],
    }
    (OUT / f"source_locality_gazetteer_{city}.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )

    by_type: dict[str, int] = {}
    for p in places.values():
        by_type[p.get("place_type") or "?"] = by_type.get(p.get("place_type") or "?", 0) + 1
    print(f"  {len(places)} unique localities (source: {source})")
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"    {t:<16} {n:>5}")
    print(f"  wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
