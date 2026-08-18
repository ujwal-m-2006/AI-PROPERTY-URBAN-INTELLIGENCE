"""Module 21 — ward-level urban analytics for the planning dashboard.

Aggregates what the platform already holds up to ward level, per city:

    infrastructure    facilities within the ward and how far the nearest is
    accessibility     transport, healthcare, education reach
    market            median price per sq.ft and listing volume, where the
                      property dataset could be matched to the ward
    pressure          listing volume relative to infrastructure provision

METHOD LABEL: every index here is a **DATA-DRIVEN SCORE** — a weighted formula
over observed counts and distances. None of it is machine learning. There is no
labelled "well-served ward" outcome to train against, so a supervised model
could be neither fitted nor validated.

Two limits that travel with every number:

  * Facility counts come from OpenStreetMap, whose completeness varies. A ward
    scoring low may be under-mapped rather than under-served, and the output
    says so.
  * Market figures exist only for wards the property dataset could be matched
    to. Wards with no matched listings report null, never zero.

    python ml/pipelines/ward_analytics.py bengaluru
    python ml/pipelines/ward_analytics.py chennai
"""

from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.gis_features import (  # noqa: E402
    haversine, load_amenities, load_wards,
)
from pipelines import city_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed"

CITY_FILES = {
    "bengaluru": ("gba_wards.geojson", "osm_amenities.json"),
    "chennai": ("chennai_wards.geojson", "osm_amenities_chennai.json"),
}

# Categories that count as infrastructure provision, grouped by service.
SERVICE_GROUPS = {
    "healthcare": ["hospital", "clinic", "pharmacy"],
    "education": ["school", "college", "university"],
    "transport": ["metro_station", "railway_station", "bus_stop", "bus_station"],
    "government": ["government_office", "police_station", "fire_station",
                   "post_office", "courthouse"],
    "daily_life": ["bank", "atm", "supermarket", "fuel", "park"],
}

# Distance at which a service stops contributing. Stated so it can be argued
# with rather than buried in a formula.
REACH_M = {"healthcare": 3000, "education": 2000, "transport": 1500,
           "government": 4000, "daily_life": 1500}


def ring_centroid(polys) -> tuple[float, float] | None:
    best, best_len = None, -1
    for poly in polys:
        ring = poly[0] if poly else None
        if ring and len(ring) > best_len:
            best, best_len = ring, len(ring)
    if not best:
        return None
    return (sum(p[0] for p in best) / len(best),
            sum(p[1] for p in best) / len(best))


def polygon_area_km2(polys) -> float:
    """Shoelace area on an equirectangular projection about the ring's own mean
    latitude. Accurate enough at ward scale, and avoids a geometry dependency."""
    total = 0.0
    for poly in polys:
        ring = poly[0] if poly else None
        if not ring or len(ring) < 4:
            continue
        lat0 = sum(p[1] for p in ring) / len(ring)
        k = math.cos(math.radians(lat0))
        s = 0.0
        for i in range(len(ring) - 1):
            x1, y1 = ring[i][0] * k, ring[i][1]
            x2, y2 = ring[i + 1][0] * k, ring[i + 1][1]
            s += x1 * y2 - x2 * y1
        total += abs(s) / 2.0
    return total * (111.32 ** 2)


def point_in_polys(lon: float, lat: float, polys) -> bool:
    from features.gis_features import _in_ring

    for poly in polys:
        if poly and _in_ring(lon, lat, poly[0]):
            if not any(_in_ring(lon, lat, h) for h in poly[1:]):
                return True
    return False


def score_component(distance_m: float | None, reach: int) -> float:
    if distance_m is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - distance_m / (2 * reach)))


def main() -> int:
    city = (sys.argv[1] if len(sys.argv) > 1 else "bengaluru").strip().lower()
    if city not in CITY_FILES:
        print(f"unknown city {city!r}")
        return 1
    wards_file, amen_file = CITY_FILES[city]
    cfg = city_config.get(city)

    print(f"\n{'=' * 70}\n  {cfg.display.upper()} — WARD ANALYTICS (Module 21)\n{'=' * 70}")

    wards = load_wards(wards_file)
    amenities = load_amenities(amen_file)
    if not wards:
        print(f"  {wards_file} not found — run the ward ingest first")
        return 2
    print(f"  {len(wards)} wards | "
          f"{sum(len(v) for v in amenities.values()):,} OSM features")

    # A sparse amenity layer makes every ward look under-served. Detect that and
    # label the output, rather than publishing "Chennai has no hospitals".
    all_cats = [c for cats in SERVICE_GROUPS.values() for c in cats]
    present = [c for c in all_cats if amenities.get(c)]
    missing = [c for c in all_cats if not amenities.get(c)]
    coverage = len(present) / len(all_cats)
    coverage_ok = coverage >= 0.75
    if not coverage_ok:
        print(f"\n  !! AMENITY COVERAGE WARNING: only {len(present)}/{len(all_cats)} "
              f"categories present ({coverage:.0%}).")
        print(f"     missing: {', '.join(missing)}")
        print("     Scores below understate provision and are marked unreliable.")

    # --- market data per ward (only where the dataset matched) -----------
    market: dict[tuple, dict[str, Any]] = {}
    try:
        from features.gis_features import add_gis_features

        df, _ = cfg.clean(city_config.load_raw(cfg))
        df, rep = add_gis_features(
            df, locality_column=cfg.locality_column, city=city,
            amenities_file=amen_file, wards_file=wards_file)
        # Ward numbers restart within each corporation, so the identity of a
        # ward is (corporation, ward_no). Grouping on the number alone would
        # merge five different wards and give them all the same market data.
        matched = df[df["gis_ward_no"].notna()].copy()
        matched["_key"] = (matched["gis_corporation"].astype(str) + "|"
                           + matched["gis_ward_no"].astype(int).astype(str))
        grouped = matched.groupby("_key")["price_per_sqft"].agg(["median", "count"])
        for key, row in grouped.iterrows():
            market[key] = {
                "median_psf": round(float(row["median"])),
                "listings": int(row["count"]),
            }
        print(f"  market data matched to {len(market)} wards "
              f"({rep['ward_match_rate']:.1%} of listings)")
    except Exception as exc:
        print(f"  market aggregation unavailable: {type(exc).__name__}: {exc}")

    # --- per-ward infrastructure ----------------------------------------
    rows: list[dict[str, Any]] = []
    for _bbox, props, polys in wards:
        centre = ring_centroid(polys)
        if centre is None:
            continue
        clng, clat = centre
        area = polygon_area_km2(polys)

        counts: dict[str, int] = {}
        nearest: dict[str, float | None] = {}
        for group, cats in SERVICE_GROUPS.items():
            inside = 0
            best = None
            for cat in cats:
                for plat, plng in amenities.get(cat, []):
                    if abs(plat - clat) > 0.25 or abs(plng - clng) > 0.25:
                        continue
                    if point_in_polys(plng, plat, polys):
                        inside += 1
                    d = haversine(clat, clng, plat, plng)
                    if best is None or d < best:
                        best = d
            counts[group] = inside
            nearest[group] = round(best) if best is not None else None

        scores = {
            g: round(100 * score_component(nearest[g], REACH_M[g]))
            for g in SERVICE_GROUPS
        }
        infra = round(sum(scores.values()) / len(scores))
        total_facilities = sum(counts.values())
        density = round(total_facilities / area, 1) if area > 0 else None

        ward_no = props.get("ward_no")
        corp = props.get("corporation")
        ward_key = f"{corp}|{int(ward_no)}" if ward_no is not None else None
        m = market.get(ward_key) if ward_key else None

        rows.append({
            "ward_no": ward_no,
            "ward_key": ward_key,
            "ward_name": props.get("ward_name"),
            "corporation": props.get("corporation"),
            "zone": props.get("zone"),
            "area_km2": round(area, 2),
            "facilities_total": total_facilities,
            "facility_density_per_km2": density,
            "counts": counts,
            "nearest_m": nearest,
            "scores": scores,
            "infrastructure_score": infra,
            "median_psf": (m or {}).get("median_psf"),
            "listings": (m or {}).get("listings"),
        })

    # --- development pressure -------------------------------------------
    # Listing volume relative to infrastructure. High market activity in a
    # weakly-served ward is the signal a planner cares about.
    listed = [r for r in rows if r["listings"]]
    max_listings = max((r["listings"] for r in listed), default=0)
    for r in rows:
        if r["listings"] and max_listings:
            activity = r["listings"] / max_listings * 100
            r["development_pressure"] = round(
                activity * (1 - r["infrastructure_score"] / 100), 1)
        else:
            r["development_pressure"] = None

    served = [r for r in rows if r["infrastructure_score"] is not None]
    served.sort(key=lambda r: r["infrastructure_score"])
    underserved = served[:15]
    best_served = served[-15:][::-1]
    pressure = sorted(
        [r for r in rows if r["development_pressure"] is not None],
        key=lambda r: -r["development_pressure"])[:15]
    priciest = sorted([r for r in rows if r["median_psf"]],
                      key=lambda r: -r["median_psf"])[:15]

    avg_infra = round(sum(r["infrastructure_score"] for r in served) / len(served), 1)
    print(f"\n  average infrastructure score: {avg_infra}/100")
    print(f"\n  {'least-served wards':<34}{'infra':>7}{'facilities':>12}")
    for r in underserved[:8]:
        print(f"  {str(r['ward_name'])[:32]:<34}{r['infrastructure_score']:>7}"
              f"{r['facilities_total']:>12}")

    payload = {
        "city": city,
        "display": cfg.display,
        "method": "DATA-DRIVEN SCORE",
        "generated_at": datetime.now(UTC).isoformat(),
        "ward_count": len(rows),
        "coverage": {
            "categories_expected": len(all_cats),
            "categories_present": len(present),
            "categories_missing": missing,
            "coverage_ratio": round(coverage, 3),
            "scores_reliable": coverage_ok,
            "warning": None if coverage_ok else (
                f"Only {len(present)} of {len(all_cats)} facility categories were "
                f"retrieved for this city. Infrastructure scores are therefore "
                f"UNDERSTATED and must not be read as evidence of poor provision. "
                f"Missing: {', '.join(missing)}. Re-run "
                f"etl/flows/ingest_osm_amenities.py {city} to complete the layer."
            ),
        },
        "summary": {
            "average_infrastructure_score": avg_infra,
            "wards_with_market_data": len([r for r in rows if r["median_psf"]]),
            "total_facilities": sum(r["facilities_total"] for r in rows),
        },
        "service_groups": SERVICE_GROUPS,
        "reach_metres": REACH_M,
        "rankings": {
            "least_served": underserved,
            "best_served": best_served,
            "highest_development_pressure": pressure,
            "highest_median_price": priciest,
        },
        "wards": rows,
        "caveats": [
            "Every index here is a weighted formula over observed counts and "
            "distances — a DATA-DRIVEN SCORE, not a machine-learning model. No "
            "labelled 'well-served ward' outcome exists to train or validate one.",
            "Facility counts come from OpenStreetMap. Completeness varies, so a "
            "low score may indicate under-mapping rather than under-provision.",
            "Distances are straight-line from the ward centroid, not road distance.",
            "Market figures cover only wards the property dataset could be "
            "matched to; unmatched wards report null, never zero.",
            "This is a research prototype and is not an official planning "
            "instrument.",
        ],
    }

    out = DATA / f"ward_analytics_{city}.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
