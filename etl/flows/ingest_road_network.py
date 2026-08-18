"""Road network ingest — Module 8 (Road Intelligence).

Source: "Bengaluru Road Width Map" on the OpenCity urban data portal, published
from BBMP. 23,238 road centreline segments, each carrying a road-hierarchy code
and **two different width figures**.

THE ONE THING THIS MODULE EXISTS TO GET RIGHT
---------------------------------------------
Every segment has `RR_WIDTH_P` and `RR_width_B`, and they are not the same
number:

    RR_WIDTH_P   min 12 m   median 18 m   max 100 m
    RR_width_B   min  6 m   median  9 m   max  50 m

Under the Bengaluru zoning regulations FAR, height and setbacks are functions of
abutting road width. Feeding the larger figure into a feasibility calculation
would roughly **double** the floor area it reports as permissible for a very
large number of plots. The naming convention (`_P` / `_B`) and the fact that no
segment is under 12 m in the first field both point to *proposed* versus
*existing* width — a road-widening proposal, not a road.

But the portal publishes **no data dictionary**, so that reading is an
inference, not a fact. This ingest therefore:

  * keeps both fields under their source names and never derives a single
    "road_width" from them;
  * records the interpretation as an explicit, labelled assumption;
  * marks the wider figure as NOT USABLE for feasibility.

Downstream, `feasibility` continues to require a user-declared road width with
a source flag. This layer may *offer* the smaller figure as a starting point.
It may never silently become the input to a FAR calculation.

TWO FURTHER LIMITS
------------------
* **Coverage is BBMP-era.** This is the old ~198-ward BBMP area, not all 369
  Greater Bengaluru wards. Coverage is measured against the ward layer and
  reported as a number, not asserted.
* **There are no road names in the dataset.** Segments cannot be identified as
  "100 Feet Road". Only hierarchy code and width are published.

    python etl/flows/ingest_road_network.py
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "roads"
OUT = ROOT / "data" / "processed"

CKAN = "https://data.opencity.in/api/3/action/package_search"
DATASET_QUERY = "Bengaluru Road Width Map"
SOURCE_URL = "https://data.opencity.in/dataset/bengaluru-road-width-map"

USER_AGENT = (
    "GBA-Property-Intelligence/0.1 (academic research prototype; "
    "contact via project README)"
)

BBOX = (77.0, 12.5, 78.2, 13.5)   # lon_min, lat_min, lon_max, lat_max

# Source field names, kept verbatim. See the module docstring before renaming
# either of these to anything that sounds like "the" road width.
F_WIDTH_PROPOSED = "RR_WIDTH_P"
F_WIDTH_EXISTING = "RR_width_B"
F_HIERARCHY = "RR_TP_HIER"
F_TYPE = "RR_TP_TYPE"
F_CODE = "RR_CD"

# Tentative expansions. The portal publishes no data dictionary, so these are
# carried in a separate field whose name says they are unverified, and are never
# substituted for the raw code.
HIERARCHY_GUESS = {
    "MA": "Major road (unverified expansion)",
    "MI": "Minor road (unverified expansion)",
    "PU": "Code 'PU' — expansion not published",
    "OR": "Outer Ring Road (unverified expansion)",
    "IR": "Inner Ring Road (unverified expansion)",
    "CR": "Code 'CR' — expansion not published",
    "PR": "Code 'PR' — expansion not published",
}

FIELD_RE = re.compile(r'<SimpleData name="([^"]+)">([^<]*)</SimpleData>')


def list_resource() -> str | None:
    resp = httpx.get(CKAN, params={"q": DATASET_QUERY, "rows": 5},
                     headers={"User-Agent": USER_AGENT}, timeout=90.0)
    resp.raise_for_status()
    for pkg in resp.json()["result"]["results"]:
        if "road width" not in pkg["title"].lower():
            continue
        for r in pkg.get("resources", []):
            if (r.get("format") or "").upper() == "KML":
                return r.get("url")
    return None


def download(url: str) -> Path | None:
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / "bengaluru_road_width.kml"
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"  cached: {dest.name} ({dest.stat().st_size:,} B)")
        return dest
    try:
        resp = httpx.get(url, headers={"User-Agent": USER_AGENT},
                         timeout=300.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  download failed: {type(exc).__name__}")
        return None
    dest.write_bytes(resp.content)
    print(f"  downloaded {len(resp.content):,} B")
    return dest


def _haversine_m(a: list[float], b: list[float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def _length_m(line: list[list[float]]) -> float:
    """Computed here rather than read from the file.

    The source carries SHAPE_LENG and SHAPE.STLength() with different values for
    the same feature (829 vs 3457 on segment 1), so at least one is in a
    projected unit this ingest cannot identify. A length derived from the
    published coordinates is the only one whose units are known.
    """
    return sum(_haversine_m(line[i], line[i + 1]) for i in range(len(line) - 1))


def _coords(text: str) -> list[list[float]]:
    line = []
    for tok in text.split():
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                line.append([round(float(parts[0]), 6), round(float(parts[1]), 6)])
            except ValueError:
                continue
    return line


def _num(raw: str) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def parse(path: Path) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    context = ET.iterparse(str(path), events=("end",))
    tag = f"{{{KML_NS['kml']}}}Placemark"

    for _event, elem in context:
        if elem.tag != tag:
            continue

        attrs = {sd.get("name"): (sd.text or "").strip()
                 for sd in elem.iter(f"{{{KML_NS['kml']}}}SimpleData")}

        lines = []
        for ls in elem.iter(f"{{{KML_NS['kml']}}}LineString"):
            c = ls.find("kml:coordinates", KML_NS)
            if c is not None and c.text:
                pts = _coords(c.text)
                if len(pts) >= 2:
                    lines.append(pts)

        elem.clear()
        if not lines:
            continue

        proposed = _num(attrs.get(F_WIDTH_PROPOSED, ""))
        existing = _num(attrs.get(F_WIDTH_EXISTING, ""))
        hier = attrs.get(F_HIERARCHY, "").strip() or None

        for line in lines:
            features.append({
                "type": "Feature",
                "properties": {
                    "road_id": attrs.get(F_CODE) or None,
                    "hierarchy_code": hier,
                    "hierarchy_interpretation_unverified": HIERARCHY_GUESS.get(hier or ""),
                    "surface_code": attrs.get(F_TYPE, "").strip() or None,
                    # Deliberately NOT called "road_width". See module docstring.
                    "width_existing_m": existing,
                    "width_proposed_m": proposed,
                    "length_m": round(_length_m(line), 1),
                },
                "geometry": {"type": "LineString", "coordinates": line},
            })

    return features


def validate(features: list[dict[str, Any]]) -> list[str]:
    problems = []
    if len(features) < 5_000:
        problems.append(f"only {len(features)} segments parsed — expected ~23,000")

    outside = 0
    for f in features:
        lon, lat = f["geometry"]["coordinates"][0]
        if not (BBOX[0] < lon < BBOX[2] and BBOX[1] < lat < BBOX[3]):
            outside += 1
    if outside > len(features) * 0.02:
        problems.append(f"{outside} segments start outside the Bengaluru bbox")

    with_existing = sum(1 for f in features if f["properties"]["width_existing_m"])
    if with_existing < len(features) * 0.5:
        problems.append(
            f"only {with_existing} of {len(features)} segments carry an existing "
            "width — the field this layer exists to serve")

    # The whole point of the module. If these ever coincide, the assumption
    # below is wrong and must be revisited before anything downstream uses it.
    both = [f["properties"] for f in features
            if f["properties"]["width_existing_m"] and f["properties"]["width_proposed_m"]]
    wider = sum(1 for p in both if p["width_proposed_m"] > p["width_existing_m"])
    if both and wider < len(both) * 0.5:
        problems.append(
            f"only {wider} of {len(both)} segments have proposed > existing width — "
            "the proposed/existing reading of RR_WIDTH_P / RR_width_B may be wrong")

    return problems


def measure_coverage(features: list[dict[str, Any]]) -> dict[str, Any]:
    """How much of the city this layer actually reaches.

    Measured against the locality gazetteer rather than asserted. This is an
    arterial-road width map, not a complete street network, and the honest way
    to say so is a number.
    """
    gaz = OUT / "locality_gazetteer_bengaluru.json"
    if not gaz.exists():
        return {"measured": False,
                "reason": "locality gazetteer not ingested; coverage not measured"}

    try:
        raw = json.loads(gaz.read_text(encoding="utf-8"))
    except ValueError:
        return {"measured": False, "reason": "gazetteer unreadable"}
    places = raw.get("places", raw) if isinstance(raw, dict) else raw
    points = [(p["lng"], p["lat"]) for p in places
              if isinstance(p, dict) and "lng" in p and "lat" in p]
    if not points:
        return {"measured": False, "reason": "no usable gazetteer points"}

    # Coarse grid over segment vertices — enough for a coverage statistic.
    cell = 0.005
    grid: dict[tuple[int, int], list[list[float]]] = {}
    for f in features:
        for pt in f["geometry"]["coordinates"]:
            grid.setdefault((int(pt[0] / cell), int(pt[1] / cell)), []).append(pt)

    def nearest_vertex_m(lng: float, lat: float, rings: int) -> float | None:
        cx, cy = int(lng / cell), int(lat / cell)
        best = None
        for i in range(cx - rings, cx + rings + 1):
            for j in range(cy - rings, cy + rings + 1):
                for pt in grid.get((i, j), ()):
                    d = _haversine_m([lng, lat], pt)
                    if best is None or d < best:
                        best = d
        return best

    buckets = {50: 0, 100: 0, 150: 0, 300: 0, 500: 0}
    for lng, lat in points:
        d = nearest_vertex_m(lng, lat, rings=2)
        if d is None:
            continue
        for t in buckets:
            if d <= t:
                buckets[t] += 1

    return {
        "measured": True,
        "basis": "distance from each gazetteer locality to the nearest road vertex",
        "localities_tested": len(points),
        "within_m": {str(k): v for k, v in buckets.items()},
        "within_pct": {str(k): round(100 * v / len(points), 1)
                       for k, v in buckets.items()},
        "note": (
            "This is a width map for the roads BBMP tracks, not the complete "
            "street network. A residential lane will usually have no mapped "
            "segment near it, and that is the dataset, not a failure of lookup."
        ),
    }


def main() -> int:
    print("Road network ingest — Module 8 (road width, BBMP via OpenCity)\n")

    print("listing resources ...")
    url = list_resource()
    if not url:
        print("  no KML resource found on the portal")
        return 2

    print("downloading (cached file is reused) ...")
    path = download(url)
    if path is None:
        return 2

    print("\nparsing ...")
    features = parse(path)
    print(f"  {len(features):,} road segments")

    problems = validate(features)
    if problems:
        print("\nVALIDATION FAILED — refusing to write output:")
        for p in problems[:10]:
            print(f"  - {p}")
        return 3

    hier: dict[str, int] = {}
    total_km = 0.0
    ex_vals, pr_vals, widened = [], [], 0
    for f in features:
        p = f["properties"]
        hier[p["hierarchy_code"] or "unknown"] = hier.get(p["hierarchy_code"] or "unknown", 0) + 1
        total_km += p["length_m"] / 1000.0
        if p["width_existing_m"]:
            ex_vals.append(p["width_existing_m"])
        if p["width_proposed_m"]:
            pr_vals.append(p["width_proposed_m"])
        if (p["width_existing_m"] and p["width_proposed_m"]
                and p["width_proposed_m"] > p["width_existing_m"]):
            widened += 1

    ex_vals.sort()
    pr_vals.sort()
    print(f"\n  network length      : {total_km:,.0f} km")
    print(f"  hierarchy codes     : {dict(sorted(hier.items(), key=lambda x: -x[1]))}")
    print(f"  existing width  (RR_width_B) : median {ex_vals[len(ex_vals)//2]:.0f} m "
          f"(range {ex_vals[0]:.0f}-{ex_vals[-1]:.0f})")
    print(f"  proposed width (RR_WIDTH_P)  : median {pr_vals[len(pr_vals)//2]:.0f} m "
          f"(range {pr_vals[0]:.0f}-{pr_vals[-1]:.0f})")
    print(f"  segments where proposed > existing: {widened:,} of {len(features):,} "
          f"({widened / len(features):.0%})")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "road_network_bengaluru.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    provenance = {
        "name": "Bengaluru road width map — road centrelines with existing and proposed width",
        "organisation": "Bruhat Bengaluru Mahanagara Palike (BBMP)",
        "source_url": SOURCE_URL,
        "dataset_name": "bengaluru-road-width-map",
        "tier": "T2",
        "availability": "DOWNLOAD",
        "licence": "Other (Public Domain) as stated by the OpenCity portal",
        "attribution": "BBMP road width map, via OpenCity Urban Data Portal",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_updated": "2025-11-27",
        "method": "http_download",
        "transformation": (
            "KML LineStrings to GeoJSON; both published width fields retained "
            "under their source names; segment length recomputed from "
            "coordinates because the two published length fields disagree"
        ),
        "access_notes": (
            f"{len(features):,} segments, {total_km:,.0f} km, sha16={digest}"
        ),
        "max_confidence": 0.80,
        "verification_status": "PARTIAL_COVERAGE",
        "assumptions": [
            "RR_width_B is read as the EXISTING carriageway width and RR_WIDTH_P "
            "as a PROPOSED/planned width. The portal publishes no data "
            "dictionary; this reading rests on the field naming and on the fact "
            f"that {widened / len(features):.0%} of segments have RR_WIDTH_P "
            "greater than RR_width_B, with no segment below 12 m in RR_WIDTH_P.",
        ],
        "caveats": [
            "NEITHER FIELD IS A SURVEYED ROAD WIDTH. Statutory FAR, height and "
            "setback depend on the width of the road abutting a specific plot, "
            "measured on the ground or taken from a sanctioned plan.",
            "RR_WIDTH_P MUST NOT BE USED FOR FEASIBILITY. If it is a proposed "
            "width, using it would report floor area that is not permissible "
            "today — median proposed width is roughly double median existing.",
            "COVERAGE IS BBMP-ERA — the former ~198-ward BBMP area, not all 369 "
            "Greater Bengaluru wards. Points outside it return UNAVAILABLE.",
            "NO ROAD NAMES are published in this dataset, so a segment cannot be "
            "identified by name.",
            "THIS IS NOT THE COMPLETE STREET NETWORK. It is a width map for the "
            "roads BBMP tracks — arterial and collector roads. Most residential "
            "lanes have no segment here. See coverage.measured below.",
            "The road-hierarchy codes (MA, MI, PU, OR, IR, CR, PR) are published "
            "without a data dictionary. Expansions shown anywhere in this "
            "project are labelled unverified.",
        ],
        "coverage": {
            "city": "bengaluru",
            "segments": len(features),
            "network_length_km": round(total_km, 1),
            "hierarchy_codes": hier,
            "measured": measure_coverage(features),
        },
    }
    (OUT / "source_road_network_bengaluru.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8")

    print(f"\n  wrote {OUT / 'road_network_bengaluru.geojson'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
