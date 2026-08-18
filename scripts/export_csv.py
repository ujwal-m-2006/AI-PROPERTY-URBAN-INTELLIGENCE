"""Export every processed layer to CSV, for Google Colab or any notebook.

The app reads GeoJSON and JSON because it does point-in-polygon work. A notebook
usually wants flat tables, so this flattens each layer once, deterministically,
into `colab/data/`.

TWO THINGS THIS PRESERVES
-------------------------
1. **Geometry is not silently dropped.** A polygon cannot become a CSV cell, so
   each row gets `centroid_lng` / `centroid_lat` plus `vertex_count`, and the
   header of every file says the geometry was reduced. A notebook that joins on
   a centroid and thinks it has a boundary would draw wrong conclusions quietly.

2. **Provenance travels.** Alongside every `X.csv` sits a row in
   `_sources.csv` carrying tier, licence, retrieval date and caveats. The
   caveats are the reason several of these tables must not be read at face
   value — the population column that is 6x too large, the road width that is a
   proposal, the survey number that settles nothing.

Deliberately NOT exported: `guidance_values.json` (local runtime state, and it
contains a person's name), and the `source_*.json` sidecars themselves, whose
content is folded into `_sources.csv`.

    python scripts/export_csv.py
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
ARTIFACTS = ROOT / "ml" / "artifacts"
OUT = ROOT / "colab" / "data"

GEOMETRY_NOTE = (
    "Geometry reduced to a centroid. This row is NOT a boundary — joining on "
    "the centroid gives you a point inside (or near) the shape, not the shape."
)


def _rings(geom: dict[str, Any]) -> list:
    t, c = geom.get("type"), geom.get("coordinates")
    if not c:
        return []
    if t == "Point":
        return [[[c]]]
    if t == "LineString":
        return [[c]]
    if t == "Polygon":
        return [c]
    if t in ("MultiPolygon", "MultiLineString"):
        return c if t == "MultiPolygon" else [[r] for r in c]
    return []


def _centroid(geom: dict[str, Any]) -> tuple[float | None, float | None, int]:
    """Mean of all vertices. Crude but honest, and labelled as a centroid."""
    xs: list[float] = []
    ys: list[float] = []
    for poly in _rings(geom):
        for ring in poly:
            for pt in ring:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    xs.append(float(pt[0]))
                    ys.append(float(pt[1]))
    if not xs:
        return None, None, 0
    return round(sum(xs) / len(xs), 6), round(sum(ys) / len(ys), 6), len(xs)


def write_csv(name: str, rows: list[dict[str, Any]], note: str) -> int:
    if not rows:
        print(f"  {name:<40} 0 rows — skipped")
        return 0
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(f"# {note}\n")
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  {name:<40} {len(rows):>6} rows, {len(keys):>2} cols")
    return len(rows)


def flatten_features(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    feats = payload.get("features", [])
    rows = []
    for f in feats:
        props = dict(f.get("properties") or {})
        geom = f.get("geometry") or {}
        lng, lat, n = _centroid(geom)
        props.update({
            "geometry_type": geom.get("type"),
            "centroid_lng": lng,
            "centroid_lat": lat,
            "vertex_count": n,
        })
        rows.append(props)
    return rows


def flatten_places(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    places = payload.get("places", payload) if isinstance(payload, dict) else payload
    return [p for p in places if isinstance(p, dict)]


def flatten_amenities(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for f in payload.get("features", []):
        if isinstance(f, dict):
            rows.append({k: v for k, v in f.items()
                         if not isinstance(v, (dict, list))})
    return rows


def flatten_ward_analytics(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    wards = payload.get("wards") or payload.get("data") or []
    rows = []
    for w in wards:
        if not isinstance(w, dict):
            continue
        flat: dict[str, Any] = {}
        for k, v in w.items():
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    if not isinstance(v2, (dict, list)):
                        flat[f"{k}_{k2}"] = v2
            elif not isinstance(v, list):
                flat[k] = v
        rows.append(flat)
    return rows


def model_comparison_rows() -> list[dict[str, Any]]:
    """The leakage table — the single most quotable ML result in the project."""
    rows = []
    for city in ("bengaluru", "chennai"):
        p = ARTIFACTS / city / "metrics.json"
        if not p.exists():
            continue
        m = json.loads(p.read_text(encoding="utf-8"))
        for algo, blocks in (m.get("model_comparison") or {}).items():
            spatial = (blocks.get("spatial_cv") or {})
            random_cv = (blocks.get("random_cv") or {})
            rows.append({
                "city": city,
                "algorithm": algo,
                "is_shipped_model": algo == m.get("algorithm"),
                "spatial_cv_r2": spatial.get("r2"),
                "spatial_cv_mae": spatial.get("mae"),
                "spatial_cv_rmse": spatial.get("rmse"),
                "spatial_cv_mape_pct": spatial.get("mape_pct"),
                "random_cv_r2": random_cv.get("r2"),
                "random_cv_mae": random_cv.get("mae"),
                "leakage_gap_r2": blocks.get("leakage_gap_r2"),
                "target": m.get("target_label"),
            })
    return rows


def source_rows() -> list[dict[str, Any]]:
    rows = []
    for p in sorted(PROCESSED.glob("source_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        rows.append({
            "layer": p.stem.replace("source_", ""),
            "name": d.get("name"),
            "organisation": d.get("organisation"),
            "tier": d.get("tier"),
            "availability": d.get("availability"),
            "licence": d.get("licence"),
            "attribution": d.get("attribution"),
            "retrieved_at": d.get("retrieved_at"),
            "source_updated": d.get("source_updated"),
            "max_confidence": d.get("max_confidence"),
            "verification_status": d.get("verification_status"),
            "source_url": d.get("source_url"),
            "transformation": d.get("transformation"),
            # The caveats are the point. Flattened, not dropped.
            "caveats": " | ".join(d.get("caveats", [])),
            "assumptions": " | ".join(d.get("assumptions", [])),
        })
    return rows


FEATURE_LAYERS = {
    "gba_wards.geojson": (
        "gba_wards.csv",
        "369 GBA wards. WARNING: _raw_tot_p is the source population field and "
        "sums to ~6x the real Greater Bengaluru total, with 125/369 rows failing "
        "male+female=total. Do NOT use it as population. " + GEOMETRY_NOTE),
    "gba_corporations.geojson": (
        "gba_corporations.csv",
        "5 city corporations, derived by dissolving wards. " + GEOMETRY_NOTE),
    "chennai_wards.geojson": (
        "chennai_wards.csv",
        "200 GCC wards. place_name and ward_name_local are DERIVED from "
        "OpenStreetMap localities, not official GCC ward names; 129/200 carry a "
        "Tamil name and the rest are deliberately blank. " + GEOMETRY_NOTE),
    "chennai_zones.geojson": ("chennai_zones.csv",
                              "15 GCC zones. " + GEOMETRY_NOTE),
    "admin_subdistricts_bengaluru.geojson": (
        "admin_taluks_bengaluru.csv",
        "District/taluk boundaries republished from LGD and Survey of India "
        "(T3, INDICATIVE). No per-boundary vintage is published and both states "
        "have reorganised taluks recently. " + GEOMETRY_NOTE),
    "admin_subdistricts_chennai.geojson": (
        "admin_taluks_chennai.csv",
        "As above, for Chennai. " + GEOMETRY_NOTE),
    "revenue_parcels.geojson": (
        "revenue_parcels.csv",
        "4,151 survey parcels from digitised Bengaluru Urban revenue sheets. "
        "COVERAGE IS PARTIAL (3 taluks, 7 hoblis). A survey number here is "
        "INDICATIVE and settles nothing about boundary or title. " + GEOMETRY_NOTE),
    "road_network_bengaluru.geojson": (
        "road_network_bengaluru.csv",
        "23,324 BBMP road segments. TWO WIDTH COLUMNS: width_existing_m and "
        "width_proposed_m. The proposed figure is larger on 100% of segments "
        "(median 18 m vs 9 m) and MUST NOT be used for FAR, height or setback. "
        + GEOMETRY_NOTE),
    "flood_locations_bengaluru.geojson": (
        "flood_locations_bengaluru.csv",
        "391 reported flooding locations from 3 BBMP layers. NOT a hazard "
        "model: no return period, depth or drainage. Absence of a nearby point "
        "is not evidence a location does not flood."),
}


def main() -> int:
    print("Exporting processed layers to CSV\n")
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0

    print("GIS layers (geometry reduced to centroids)")
    for src, (name, note) in FEATURE_LAYERS.items():
        p = PROCESSED / src
        if not p.exists():
            print(f"  {name:<40} source missing — skipped")
            continue
        total += write_csv(name, flatten_features(p), note)

    print("\nGazetteers and amenities")
    for city in ("bengaluru", "chennai"):
        p = PROCESSED / f"locality_gazetteer_{city}.json"
        if p.exists():
            total += write_csv(
                f"localities_{city}.csv", flatten_places(p),
                f"OpenStreetMap localities for {city} (T3, ODbL). name_local is "
                "the local-script name where OSM carries one.")
    for city, fname in (("bengaluru", "osm_amenities.json"),
                        ("chennai", "osm_amenities_chennai.json")):
        p = PROCESSED / fname
        if p.exists():
            total += write_csv(
                f"amenities_{city}.csv", flatten_amenities(p),
                f"OpenStreetMap amenities for {city} (T3, ODbL). Nearest is not "
                "jurisdictional — the closest government office is often not "
                "the one with jurisdiction.")

    print("\nWard analytics")
    for city in ("bengaluru", "chennai"):
        p = PROCESSED / f"ward_analytics_{city}.json"
        if p.exists():
            total += write_csv(
                f"ward_analytics_{city}.csv", flatten_ward_analytics(p),
                f"Per-ward service accessibility for {city}. Scores are weighted "
                "formulas, NOT machine learning, and a missing input is reported "
                "as UNAVAILABLE rather than scored zero.")

    print("\nML results")
    total += write_csv(
        "model_comparison.csv", model_comparison_rows(),
        "Every algorithm under two CV schemes. spatial_cv_r2 is the honest "
        "number and is what the shipped model was selected on; leakage_gap_r2 is "
        "how much random k-fold overstates it by letting neighbouring "
        "properties cross folds.")

    print("\nProvenance")
    total += write_csv(
        "_sources.csv", source_rows(),
        "One row per ingested layer: tier, licence, retrieval date and the "
        "caveats that constrain how each table may be read.")

    print(f"\n{'=' * 60}")
    print(f"  {total:,} rows across {len(list(OUT.glob('*.csv')))} CSV files")
    print(f"  {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
