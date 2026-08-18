"""Phase 5 — proximity intelligence ingest (Modules 9, 10, 11).

Pulls transport nodes, government offices and essential services for the Greater
Bengaluru bounding box from the OpenStreetMap Overpass API.

OSM is tier T3 (community), so everything derived from it is capped at 0.70
confidence. Attribution under ODbL is mandatory and is written into the
provenance record.

Run:  python etl/flows/ingest_osm_amenities.py
Re-run is safe; output is overwritten.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "processed"

# The main instance returns 406 for this client; community mirrors accept it.
# Tried in order, first success wins.
OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
# S,W,N,E per city. Bengaluru remains the default so existing invocations
# (`python etl/flows/ingest_osm_amenities.py`) behave exactly as before.
CITY_BBOX = {
    "bengaluru": "12.70,77.30,13.25,77.90",
    "chennai": "12.83,80.10,13.25,80.35",
}
CITY_OUTPUT = {
    "bengaluru": "osm_amenities.json",
    "chennai": "osm_amenities_chennai.json",
}
CITY = "bengaluru"
BBOX = CITY_BBOX[CITY]

USER_AGENT = (
    "GBA-Property-Intelligence/0.1 (academic research prototype; "
    "contact via project README)"
)

# category -> Overpass filters. Kept explicit rather than clever so a reviewer
# can see exactly what is being requested.
CATEGORIES: dict[str, list[str]] = {
    "metro_station": ['node["railway"="station"]["station"="subway"]',
                      'node["railway"="subway_entrance"]'],
    "railway_station": ['node["railway"="station"]["station"!="subway"]',
                        'node["railway"="halt"]'],
    "bus_stop": ['node["highway"="bus_stop"]'],
    "bus_station": ['node["amenity"="bus_station"]', 'way["amenity"="bus_station"]'],
    "airport": ['way["aeroway"="aerodrome"]', 'node["aeroway"="aerodrome"]'],

    "government_office": ['node["office"="government"]', 'way["office"="government"]',
                          'node["amenity"="townhall"]', 'way["amenity"="townhall"]'],
    "police_station": ['node["amenity"="police"]', 'way["amenity"="police"]'],
    "fire_station": ['node["amenity"="fire_station"]', 'way["amenity"="fire_station"]'],
    "post_office": ['node["amenity"="post_office"]'],
    "courthouse": ['node["amenity"="courthouse"]', 'way["amenity"="courthouse"]'],

    "hospital": ['node["amenity"="hospital"]', 'way["amenity"="hospital"]'],
    "clinic": ['node["amenity"="clinic"]', 'node["amenity"="doctors"]'],
    "pharmacy": ['node["amenity"="pharmacy"]'],

    "school": ['node["amenity"="school"]', 'way["amenity"="school"]'],
    "college": ['node["amenity"="college"]', 'way["amenity"="college"]'],
    "university": ['node["amenity"="university"]', 'way["amenity"="university"]'],

    "bank": ['node["amenity"="bank"]'],
    "atm": ['node["amenity"="atm"]'],
    "fuel": ['node["amenity"="fuel"]'],
    "supermarket": ['node["shop"="supermarket"]', 'way["shop"="supermarket"]'],
    "park": ['way["leisure"="park"]', 'node["leisure"="park"]'],
    "lake": ['way["natural"="water"]', 'way["water"="lake"]'],
}

# Which categories are government bodies — Module 10 needs this separation.
GOVERNMENT = {
    "government_office", "police_station", "fire_station", "post_office", "courthouse",
}


def build_query(filters: list[str]) -> str:
    body = "\n".join(f"  {f}({BBOX});" for f in filters)
    return f"[out:json][timeout:180];\n(\n{body}\n);\nout center tags;"


def fetch(category: str, filters: list[str]) -> list[dict[str, Any]]:
    query = build_query(filters)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    payload = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = httpx.post(
                endpoint, data={"data": query}, headers=headers, timeout=200.0
            )
            resp.raise_for_status()
            payload = resp.json()
            break
        except (httpx.HTTPError, ValueError) as exc:
            print(f" [{endpoint.split('/')[2]}: {type(exc).__name__}]", end="")
            time.sleep(12)  # mirrors throttle aggressively; back off properly

    if payload is None:
        print("  FAILED on all endpoints", end="")
        return []

    features = []
    for el in payload.get("elements", []):
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:en")
        if not name and category not in ("bus_stop", "atm"):
            continue  # unnamed facilities are not useful to show a user
        features.append(
            {
                "id": f"{el.get('type','n')}/{el.get('id')}",
                "category": category,
                "name": name,
                "name_kn": tags.get("name:kn"),
                "operator": tags.get("operator"),
                "is_government": (
                    category in GOVERNMENT
                    or str(tags.get("operator:type", "")).lower() in ("government", "public")
                ),
                "lat": round(float(lat), 6),
                "lng": round(float(lon), 6),
            }
        )
    return features


def main() -> int:
    global CITY, BBOX
    import sys

    if len(sys.argv) > 1:
        CITY = sys.argv[1].strip().lower()
        if CITY not in CITY_BBOX:
            print(f"unknown city {CITY!r}; choose from {list(CITY_BBOX)}")
            return 1
        BBOX = CITY_BBOX[CITY]

    print(f"Overpass ingest for {CITY} bbox {BBOX}")
    print("OpenStreetMap contributors, ODbL. Tier T3 — capped at 0.70 confidence.\n")

    # Resumable: keep whatever a previous run already retrieved and only fetch
    # categories that are still empty. Free Overpass mirrors rate-limit hard, so
    # a full re-run would waste the categories that already succeeded.
    existing_path = OUT / CITY_OUTPUT[CITY]
    all_features: list[dict[str, Any]] = []
    have: set[str] = set()
    if existing_path.exists():
        try:
            prev = json.loads(existing_path.read_text(encoding="utf-8"))
            all_features = prev.get("features", [])
            have = {f["category"] for f in all_features}
            print(f"  resuming: {len(all_features):,} features already held "
                  f"across {len(have)} categories\n")
        except (ValueError, KeyError):
            all_features, have = [], set()

    counts: dict[str, int] = {c: sum(1 for f in all_features if f["category"] == c)
                              for c in have}

    for category, filters in CATEGORIES.items():
        if category in have:
            print(f"  {category:<20}{counts[category]:>6}  (kept)")
            continue
        print(f"  {category:<20}", end="", flush=True)
        found = fetch(category, filters)
        counts[category] = len(found)
        all_features.extend(found)
        print(f"{len(found):>6}")
        time.sleep(5)  # be polite to a free community endpoint

    OUT.mkdir(parents=True, exist_ok=True)
    out_name = CITY_OUTPUT[CITY]
    (OUT / out_name).write_text(
        json.dumps({"features": all_features}), encoding="utf-8"
    )

    provenance = {
        "name": "OpenStreetMap amenities, transport and government offices",
        "organisation": "OpenStreetMap contributors",
        "source_url": "https://overpass-api.de/api/interpreter",
        "dataset_name": "overpass-bengaluru-amenities",
        "tier": "T3",
        "availability": "API",
        "licence": "Open Database License (ODbL) 1.0",
        "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "attribution": "© OpenStreetMap contributors",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "method": "http_download",
        "transformation": (
            "Overpass QL per category; nodes and way centroids; unnamed features "
            "dropped except bus stops and ATMs"
        ),
        "access_notes": f"bbox={BBOX}; {len(all_features)} features; counts={counts}",
        "max_confidence": 0.70,
        "verification_status": "COMMUNITY_SOURCED",
        "caveats": [
            "OSM completeness varies across Greater Bengaluru; absence of a "
            "facility in this layer is not evidence that none exists",
            "Government/private classification relies on OSM tagging and is "
            "unreliable; it is not an official directory",
            "Jurisdiction is NOT determined by proximity — the nearest office is "
            "not necessarily the office with jurisdiction",
        ],
    }
    prov_name = f"source_{out_name}"
    (OUT / prov_name).write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    total = len(all_features)
    print(f"\n  total {total:,} features across {len(counts)} categories")
    print(f"  wrote {OUT / out_name}")
    return 0 if total else 2


if __name__ == "__main__":
    raise SystemExit(main())
