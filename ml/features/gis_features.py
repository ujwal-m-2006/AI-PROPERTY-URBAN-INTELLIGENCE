"""GIS-derived ML features (your Module 10 — GIS as feature engineering).

This module is the join between the mapping work and the model. It takes a
dataset whose only location signal is a locality string, resolves that string to
coordinates via the OSM gazetteer, and computes distance features against the
OSM amenity layer and the official ward boundaries.

Produced per property:

    metro_distance_m          railway_distance_m       bus_distance_m
    hospital_distance_m       school_distance_m        govt_office_distance_m
    road_distance_m           park_distance_m          bank_distance_m
    amenity_count_1km         ward_no / corporation / zone

HONESTY CEILING — stated once, applies to every feature here:
resolution is LOCALITY level, not property level. Two flats on the same street
get identical GIS features. The gazetteer match is derived evidence (T5, capped
at 0.70), so nothing built on it may claim higher confidence.

That limitation is real and is why these features help but do not transform the
model: they explain between-locality variation, not within-locality variation.
"""

from __future__ import annotations

import json
import math
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed"

EARTH_R = 6_371_000.0

# Amenity categories -> feature name. Uses the categories actually ingested by
# etl/flows/ingest_osm_amenities.py.
DISTANCE_FEATURES: dict[str, list[str]] = {
    "metro_distance_m": ["metro_station"],
    "railway_distance_m": ["railway_station"],
    "bus_distance_m": ["bus_stop", "bus_station"],
    "hospital_distance_m": ["hospital"],
    "school_distance_m": ["school"],
    "college_distance_m": ["college", "university"],
    "govt_office_distance_m": [
        "government_office", "police_station", "post_office", "courthouse"
    ],
    "bank_distance_m": ["bank"],
    "park_distance_m": ["park"],
    "supermarket_distance_m": ["supermarket"],
}

# Distance assigned when no facility of a category exists anywhere in the city
# layer. Chosen to be clearly outside any real distance so the model can learn
# "absent" rather than being handed a fabricated number.
NO_FACILITY_SENTINEL_M = 50_000


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


# --- gazetteer -----------------------------------------------------------


def load_gazetteer(city: str) -> dict[str, dict[str, Any]]:
    path = DATA / f"locality_gazetteer_{city}.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {p["name"].strip().lower(): p for p in payload.get("places", [])}


def _normalise(name: str) -> str:
    s = str(name).strip().lower()
    # Dataset localities carry noise like "Whitefield ", "JP Nagar Phase 7".
    for token in (" phase", " stage", " block", " main road", " layout"):
        if token in s:
            s = s.split(token)[0]
    return s.strip(" ,.-")


def resolve_localities(
    localities: pd.Series, gazetteer: dict[str, dict[str, Any]]
) -> tuple[pd.Series, pd.Series, float]:
    """Locality string -> (lat, lng). Returns coverage as the third value."""
    if not gazetteer:
        nan = pd.Series([None] * len(localities), index=localities.index)
        return nan, nan, 0.0

    names = list(gazetteer)
    cache: dict[str, dict[str, Any] | None] = {}

    def match(raw: object) -> dict[str, Any] | None:
        key = _normalise(str(raw))
        if key in cache:
            return cache[key]
        hit = gazetteer.get(key)
        if hit is None:
            close = get_close_matches(key, names, n=1, cutoff=0.87)
            hit = gazetteer[close[0]] if close else None
        cache[key] = hit
        return hit

    matched = localities.map(match)
    lat = matched.map(lambda m: m["lat"] if m else None)
    lng = matched.map(lambda m: m["lng"] if m else None)
    coverage = float(matched.notna().mean())
    return lat, lng, coverage


# --- amenity index -------------------------------------------------------


def load_amenities(city_file: str) -> dict[str, list[tuple[float, float]]]:
    path = DATA / city_file
    if not path.exists():
        return {}
    features = json.loads(path.read_text(encoding="utf-8")).get("features", [])
    index: dict[str, list[tuple[float, float]]] = {}
    for f in features:
        index.setdefault(f["category"], []).append((f["lat"], f["lng"]))
    return index


def nearest_distance(
    lat: float, lng: float, points: list[tuple[float, float]]
) -> float | None:
    """Nearest point, with a cheap degree-box prefilter before the trig."""
    if not points:
        return None
    best = float("inf")
    # ~0.09 deg latitude is about 10 km; widen if nothing is found.
    for window in (0.09, 0.25, 1.0):
        for plat, plng in points:
            if abs(plat - lat) > window or abs(plng - lng) > window:
                continue
            d = haversine(lat, lng, plat, plng)
            if d < best:
                best = d
        if best < float("inf"):
            break
    return best if best < float("inf") else None


def count_within(
    lat: float, lng: float, index: dict[str, list[tuple[float, float]]], radius_m: float
) -> int:
    n = 0
    window = radius_m / 111_000.0 * 1.2
    for points in index.values():
        for plat, plng in points:
            if abs(plat - lat) > window or abs(plng - lng) > window:
                continue
            if haversine(lat, lng, plat, plng) <= radius_m:
                n += 1
    return n


# --- ward join -----------------------------------------------------------


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


def load_wards(wards_file: str) -> list[tuple[tuple, dict, list]]:
    path = DATA / wards_file
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for f in payload["features"]:
        geom = f["geometry"]
        polys = (
            [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        )
        xs = [p[0] for poly in polys for ring in poly for p in ring]
        ys = [p[1] for poly in polys for ring in poly for p in ring]
        out.append(((min(xs), min(ys), max(xs), max(ys)), f["properties"], polys))
    return out


def ward_for(lat: float, lng: float, wards: list) -> dict | None:
    for (minx, miny, maxx, maxy), props, polys in wards:
        if not (minx <= lng <= maxx and miny <= lat <= maxy):
            continue
        for poly in polys:
            if poly and _in_ring(lng, lat, poly[0]):
                if not any(_in_ring(lng, lat, hole) for hole in poly[1:]):
                    return props
    return None


# --- main entry ----------------------------------------------------------


def add_gis_features(
    df: pd.DataFrame,
    *,
    locality_column: str,
    city: str,
    amenities_file: str,
    wards_file: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach GIS features to a property dataframe.

    Returns the enriched frame and a report describing coverage, so the
    limitations travel with the data instead of being lost.
    """
    report: dict[str, Any] = {"city": city, "rows": int(len(df))}

    gazetteer = load_gazetteer(city)
    report["gazetteer_size"] = len(gazetteer)

    lat, lng, coverage = resolve_localities(df[locality_column], gazetteer)
    df = df.copy()
    df["gis_lat"] = lat
    df["gis_lng"] = lng
    report["locality_match_rate"] = round(coverage, 4)

    amenities = load_amenities(amenities_file)
    report["amenity_categories"] = len(amenities)
    report["amenity_features"] = sum(len(v) for v in amenities.values())

    wards = load_wards(wards_file)
    report["ward_polygons"] = len(wards)

    # Compute once per unique resolved coordinate, not per row — localities
    # repeat heavily, so this is the difference between seconds and minutes.
    unique_points = (
        df.loc[df["gis_lat"].notna(), ["gis_lat", "gis_lng"]]
        .drop_duplicates()
        .itertuples(index=False)
    )

    cache: dict[tuple[float, float], dict[str, Any]] = {}
    for plat, plng in unique_points:
        row: dict[str, Any] = {}
        for feature, categories in DISTANCE_FEATURES.items():
            points: list[tuple[float, float]] = []
            for c in categories:
                points.extend(amenities.get(c, []))
            d = nearest_distance(plat, plng, points)
            row[feature] = (
                round(d) if d is not None
                else (NO_FACILITY_SENTINEL_M if points else None)
            )
        row["amenity_count_1km"] = count_within(plat, plng, amenities, 1000)

        w = ward_for(plat, plng, wards)
        row["gis_ward_no"] = w.get("ward_no") if w else None
        row["gis_corporation"] = w.get("corporation") if w else None
        row["gis_zone"] = w.get("zone") if w else None
        cache[(plat, plng)] = row

    feature_names = list(DISTANCE_FEATURES) + [
        "amenity_count_1km", "gis_ward_no", "gis_corporation", "gis_zone"
    ]
    for name in feature_names:
        df[name] = [
            cache.get((r.gis_lat, r.gis_lng), {}).get(name)
            if pd.notna(r.gis_lat) else None
            for r in df.itertuples(index=False)
        ]

    report["unique_locations"] = len(cache)
    report["ward_match_rate"] = round(float(df["gis_ward_no"].notna().mean()), 4)
    report["features_added"] = feature_names
    report["caveats"] = [
        "Locality-level resolution: properties in the same locality share "
        "identical GIS features",
        "Locality->coordinate match is derived (T5) from OpenStreetMap place "
        "names, capped at 0.70 confidence",
        "Straight-line distance, not road or walking distance",
        f"{NO_FACILITY_SENTINEL_M} m is a sentinel meaning 'no facility of this "
        "category in the city layer', not a measured distance",
    ]
    return df, report
