"""Revenue layer ingest — taluk, hobli, village and survey number.

Source: "Bengaluru Urban Revenue Maps" on the OpenCity urban data portal — one
KML per hobli, each parcelled into survey numbers, with TALUK / HOBLI / VILLAGE
carried in every placemark's description.

This fills the gap that Module 1 has reported as UNAVAILABLE since the first
audit: district / taluk / hobli / village. It also gives Module 2 a survey
number for the first time.

TWO LIMITS THAT MUST TRAVEL WITH EVERY RESULT
---------------------------------------------
1. **Coverage is partial.** Only the taluks and hoblis published in this dataset
   are present. A point outside them returns UNAVAILABLE, never a guess.

2. **A survey number here is indicative, not a legal determination.** These are
   digitised revenue sheets. Boundary disputes, sub-divisions and conversions are
   settled by the Sub-Registrar and a licensed surveyor, not by this layer.

    python etl/flows/ingest_revenue_maps.py
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "revenue"
OUT = ROOT / "data" / "processed"

CKAN = "https://data.opencity.in/api/3/action/package_search"
DATASET_QUERY = "Bengaluru Urban Revenue Maps"
SOURCE_URL = "https://data.opencity.in/dataset/bengaluru-urban-revenue-maps"

USER_AGENT = (
    "GBA-Property-Intelligence/0.1 (academic research prototype; "
    "contact via project README)"
)

# Fields carried in each placemark's CDATA description.
FIELD_RE = re.compile(r"<B>([A-Z_0-9]+)</B>\s*=\s*([^<]*)")


def list_resources() -> list[dict[str, str]]:
    resp = httpx.get(CKAN, params={"q": DATASET_QUERY, "rows": 3},
                     headers={"User-Agent": USER_AGENT}, timeout=90.0)
    resp.raise_for_status()
    for pkg in resp.json()["result"]["results"]:
        if "revenue map" in pkg["title"].lower() and "bengaluru" in pkg["title"].lower():
            return [
                {"name": r.get("name", ""), "url": r.get("url", "")}
                for r in pkg.get("resources", [])
                if (r.get("format") or "").upper() == "KML"
            ]
    return []


def download(resources: list[dict[str, str]]) -> list[Path]:
    RAW.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, r in enumerate(resources, 1):
        safe = re.sub(r"[^A-Za-z0-9]+", "_", r["name"])[:80] or f"map_{i}"
        dest = RAW / f"{safe}.kml"
        if dest.exists() and dest.stat().st_size > 1000:
            paths.append(dest)
            continue
        try:
            resp = httpx.get(r["url"], headers={"User-Agent": USER_AGENT},
                             timeout=120.0, follow_redirects=True)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            paths.append(dest)
            print(f"  [{i:>3}/{len(resources)}] {safe[:58]:<58} "
                  f"{len(resp.content):>8,} B")
        except httpx.HTTPError as exc:
            print(f"  [{i:>3}/{len(resources)}] FAILED {safe[:48]} ({type(exc).__name__})")
        time.sleep(0.6)   # polite to a community portal
    return paths


def _attrs(description: str) -> dict[str, str]:
    return {k: v.strip() for k, v in FIELD_RE.findall(description or "")}


def _ring(text: str) -> list[list[float]]:
    ring = []
    for tok in text.split():
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                ring.append([round(float(parts[0]), 7), round(float(parts[1]), 7)])
            except ValueError:
                continue
    return ring


def _polygons(pm: ET.Element) -> list:
    polys = []
    for poly in pm.iterfind(".//kml:Polygon", KML_NS):
        outer = poly.find(".//kml:outerBoundaryIs//kml:coordinates", KML_NS)
        if outer is None or not outer.text:
            continue
        ring = _ring(outer.text)
        if len(ring) < 4:
            continue
        rings = [ring]
        for inner in poly.iterfind(".//kml:innerBoundaryIs//kml:coordinates", KML_NS):
            if inner.text:
                hole = _ring(inner.text)
                if len(hole) >= 4:
                    rings.append(hole)
        polys.append(rings)
    return polys


def _clean_taluk(v: str) -> str:
    # "Bangalore(East)" -> "Bangalore East"
    return re.sub(r"\s*\(\s*([^)]+)\s*\)", r" \1", v).strip()


def parse(paths: list[Path]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for p in paths:
        try:
            tree = ET.parse(p)
        except ET.ParseError:
            print(f"  unparseable: {p.name}")
            continue
        for pm in tree.iterfind(".//kml:Placemark", KML_NS):
            desc = pm.findtext("kml:description", default="", namespaces=KML_NS)
            a = _attrs(desc)
            polys = _polygons(pm)
            if not polys:
                continue
            taluk = _clean_taluk(a.get("TALUK", ""))
            hobli = a.get("HOBLI", "").strip()
            village = a.get("VILLAGE", "").strip()
            if not (taluk or hobli or village):
                continue
            survey = a.get("DXF_TEXT", "").strip() or None
            features.append({
                "type": "Feature",
                "properties": {
                    "taluk": taluk or None,
                    "hobli": hobli or None,
                    "village": village or None,
                    "survey_number": survey,
                    "pcode": a.get("PCODE") or None,
                    "district": "Bengaluru Urban",
                    "source_sheet": p.stem,
                },
                "geometry": (
                    {"type": "Polygon", "coordinates": polys[0]}
                    if len(polys) == 1
                    else {"type": "MultiPolygon", "coordinates": polys}
                ),
            })
    return features


def validate(features: list[dict[str, Any]]) -> list[str]:
    problems = []
    if len(features) < 100:
        problems.append(f"only {len(features)} parcels parsed — expected hundreds")
    outside = 0
    for f in features:
        geom = f["geometry"]
        polys = ([geom["coordinates"]] if geom["type"] == "Polygon"
                 else geom["coordinates"])
        for poly in polys:
            for lon, lat in poly[0]:
                if not (77.0 < lon < 78.2 and 12.5 < lat < 13.5):
                    outside += 1
                    break
            break
    if outside:
        problems.append(f"{outside} parcels have vertices outside the Bengaluru bbox")
    return problems


def main() -> int:
    print("Revenue layer ingest — taluk / hobli / village / survey number\n")

    print("listing resources ...")
    resources = list_resources()
    if not resources:
        print("  no KML resources found on the portal")
        return 2
    print(f"  {len(resources)} KML sheets published\n")

    print("downloading (cached files are reused) ...")
    paths = download(resources)
    print(f"\n  {len(paths)} sheets available locally")

    print("\nparsing ...")
    features = parse(paths)
    print(f"  {len(features):,} survey parcels")

    problems = validate(features)
    if problems:
        print("\nVALIDATION FAILED — refusing to write output:")
        for p in problems[:10]:
            print(f"  - {p}")
        return 3

    taluks: dict[str, set] = {}
    villages: set = set()
    surveys = 0
    for f in features:
        pr = f["properties"]
        if pr["taluk"]:
            taluks.setdefault(pr["taluk"], set()).add(pr["hobli"])
        if pr["village"]:
            villages.add((pr["taluk"], pr["hobli"], pr["village"]))
        if pr["survey_number"]:
            surveys += 1

    print(f"\n  taluks   : {len(taluks)}")
    for t, hs in sorted(taluks.items()):
        print(f"    {t:<22} {len(hs)} hobli(s): {', '.join(sorted(h for h in hs if h))}")
    print(f"  villages : {len(villages)}")
    print(f"  parcels with a survey number: {surveys:,} of {len(features):,}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "revenue_parcels.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8")

    digest = hashlib.sha256(
        b"".join(sorted(p.read_bytes() for p in paths[:5]))).hexdigest()[:16]
    provenance = {
        "name": "Bengaluru Urban revenue maps — taluk, hobli, village, survey number",
        "organisation": "Karnataka Revenue Department (digitised sheets)",
        "source_url": SOURCE_URL,
        "dataset_name": "bengaluru-urban-revenue-maps",
        "tier": "T2",
        "availability": "DOWNLOAD",
        "licence": "As published by the OpenCity urban data portal",
        "attribution": "Revenue maps via OpenCity Urban Data Portal",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_updated": date(2020, 1, 1).isoformat(),
        "method": "http_download",
        "transformation": (
            "One KML per hobli sheet; TALUK/HOBLI/VILLAGE and survey number read "
            "from each placemark's description; geometry converted to GeoJSON"
        ),
        "access_notes": f"{len(paths)} sheets, {len(features)} parcels, sha16={digest}",
        "max_confidence": 0.80,
        "verification_status": "PARTIAL_COVERAGE",
        "caveats": [
            "COVERAGE IS PARTIAL — only the taluks and hoblis published in this "
            "dataset are present. Points outside them return UNAVAILABLE.",
            "A survey number from a digitised revenue sheet is INDICATIVE. It is "
            "not a legal determination of boundary or title; those are settled by "
            "the Sub-Registrar and a licensed surveyor.",
            "Sheet vintage is not stated per file; treat as historical and "
            "re-verify before relying on it.",
        ],
        "coverage": {
            "district": "Bengaluru Urban",
            "taluks": sorted(taluks),
            "hobli_count": sum(len(h) for h in taluks.values()),
            "village_count": len(villages),
        },
    }
    (OUT / "source_revenue_parcels.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8")

    print(f"\n  wrote {OUT / 'revenue_parcels.geojson'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
