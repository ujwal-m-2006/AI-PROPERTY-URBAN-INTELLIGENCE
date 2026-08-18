"""Module 12 — known flooding locations, from BBMP.

Audit task R7 located this dataset and left it uningested with a specific
instruction, which this flow obeys:

    "It is point data, not inundation geometry, and no return period, depth or
     methodology is attached. That is enough to say 'a known flooding location
     is recorded N metres away'. It is not enough to compute a flood risk
     score."

So this ingests the points and nothing more. The risk score continues to list
flood as EXCLUDED. Turning a set of reported flooding spots into a 0-100 risk
number would imply a hazard model — return periods, drainage capacity, terrain —
that nobody has built and this data cannot support.

WHAT THE DATASET IS
-------------------
Three KML layers published by BBMP through the OpenCity portal, licence Other
(Public Domain):

  * locations vulnerable to flooding
  * flood-prone locations
  * BBMP low-lying areas

They are historical reports of where flooding has occurred or is expected. They
are not a prediction, not a boundary, and absence of a point near a property is
NOT evidence that it does not flood — only that none was reported in this set.

    python etl/flows/ingest_flood_locations.py
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "flood"
OUT = ROOT / "data" / "processed"

CKAN = "https://data.opencity.in/api/3/action/package_search"
DATASET_QUERY = "Flooding Locations in Bengaluru Urban"
SOURCE_URL = "https://data.opencity.in/dataset/flooding-locations-in-bengaluru-urban"

USER_AGENT = (
    "GBA-Property-Intelligence/0.1 (academic research prototype; "
    "contact via project README)"
)

BBOX = (77.0, 12.5, 78.2, 13.5)

# Each resource says something slightly different; keep them distinguishable
# rather than merging into one undifferentiated "flood" blob.
KIND_HINTS = (
    ("low lying", "BBMP low-lying area"),
    ("vulnerable", "Location vulnerable to flooding"),
    ("flood prone", "Flood-prone location"),
    ("flood", "Reported flooding location"),
)

NOT_A_HAZARD_MODEL = (
    "These are reported flooding locations, not a hazard model. No return "
    "period, depth, drainage capacity or terrain analysis is attached. "
    "Distance to the nearest reported point is NOT a flood risk score."
)

ABSENCE_MEANS_NOTHING = (
    "No reported point nearby does NOT mean the property does not flood. It "
    "means none was recorded in this dataset."
)


def _kind(resource_name: str) -> str:
    low = resource_name.lower()
    for needle, label in KIND_HINTS:
        if needle in low:
            return label
    return "Reported flooding location"


def list_resources() -> list[dict[str, str]]:
    resp = httpx.get(CKAN, params={"q": DATASET_QUERY, "rows": 5},
                     headers={"User-Agent": USER_AGENT}, timeout=90.0)
    resp.raise_for_status()
    for pkg in resp.json()["result"]["results"]:
        if "flooding" not in pkg["title"].lower():
            continue
        return [{"name": r.get("name", ""), "url": r.get("url", "")}
                for r in pkg.get("resources", [])
                if (r.get("format") or "").upper() == "KML"]
    return []


def download(resources: list[dict[str, str]]) -> list[tuple[Path, str]]:
    RAW.mkdir(parents=True, exist_ok=True)
    out: list[tuple[Path, str]] = []
    for i, r in enumerate(resources, 1):
        safe = re.sub(r"[^A-Za-z0-9]+", "_", r["name"])[:60] or f"flood_{i}"
        dest = RAW / f"{safe}.kml"
        if not (dest.exists() and dest.stat().st_size > 200):
            try:
                resp = httpx.get(r["url"], headers={"User-Agent": USER_AGENT},
                                 timeout=180.0, follow_redirects=True)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                print(f"  [{i}/{len(resources)}] {safe[:44]:<44} "
                      f"{len(resp.content):>8,} B")
            except httpx.HTTPError as exc:
                print(f"  [{i}/{len(resources)}] FAILED {safe[:40]} "
                      f"({type(exc).__name__})")
                continue
        else:
            print(f"  [{i}/{len(resources)}] cached {safe[:44]}")
        out.append((dest, _kind(r["name"])))
    return out


def _points(pm: ET.Element) -> list[list[float]]:
    """Every coordinate a placemark carries, whatever geometry it uses."""
    pts: list[list[float]] = []
    for c in pm.iter(f"{{{KML_NS['kml']}}}coordinates"):
        if not c.text:
            continue
        for tok in c.text.split():
            parts = tok.split(",")
            if len(parts) >= 2:
                try:
                    pts.append([round(float(parts[0]), 6),
                                round(float(parts[1]), 6)])
                except ValueError:
                    continue
    return pts


def parse(paths: list[tuple[Path, str]]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()

    for path, kind in paths:
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            print(f"  unparseable: {path.name}")
            continue

        kept = 0
        for pm in tree.iter(f"{{{KML_NS['kml']}}}Placemark"):
            name = (pm.findtext("kml:name", default="", namespaces=KML_NS) or "").strip()
            pts = _points(pm)
            if not pts:
                continue
            # A polygon or line is represented by its first vertex — the layer
            # is treated as points throughout, which is what it is.
            lon, lat = pts[0]
            if not (BBOX[0] < lon < BBOX[2] and BBOX[1] < lat < BBOX[3]):
                continue
            key = (round(lon, 5), round(lat, 5))
            if key in seen:
                continue
            seen.add(key)
            features.append({
                "type": "Feature",
                "properties": {
                    "name": name or None,
                    "kind": kind,
                    "source_layer": path.stem,
                },
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            })
            kept += 1
        print(f"    {path.stem[:46]:<46} {kept:>5} points")

    return features


def validate(features: list[dict[str, Any]]) -> list[str]:
    problems = []
    if len(features) < 20:
        problems.append(f"only {len(features)} points parsed — expected dozens")
    outside = sum(
        1 for f in features
        if not (BBOX[0] < f["geometry"]["coordinates"][0] < BBOX[2]
                and BBOX[1] < f["geometry"]["coordinates"][1] < BBOX[3]))
    if outside:
        problems.append(f"{outside} points outside the Bengaluru bbox")
    return problems


def main() -> int:
    print("Flood location ingest — Module 12 (BBMP via OpenCity)\n")

    print("listing resources ...")
    resources = list_resources()
    if not resources:
        print("  no KML resources found on the portal")
        return 2
    print(f"  {len(resources)} KML layers published\n")

    print("downloading ...")
    paths = download(resources)
    if not paths:
        return 2

    print("\nparsing ...")
    features = parse(paths)
    print(f"  {len(features):,} distinct reported locations")

    problems = validate(features)
    if problems:
        print("\nVALIDATION FAILED — refusing to write output:")
        for p in problems[:10]:
            print(f"  - {p}")
        return 3

    kinds: dict[str, int] = {}
    for f in features:
        k = f["properties"]["kind"]
        kinds[k] = kinds.get(k, 0) + 1
    print("\n  by kind:")
    for k, n in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"    {k:<34} {n:>5}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "flood_locations_bengaluru.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8")

    digest = hashlib.sha256(
        b"".join(sorted(p.read_bytes() for p, _ in paths))).hexdigest()[:16]
    provenance = {
        "name": "Reported flooding locations, Bengaluru Urban",
        "organisation": "Bruhat Bengaluru Mahanagara Palike (BBMP)",
        "source_url": SOURCE_URL,
        "dataset_name": "flooding-locations-in-bengaluru-urban",
        "tier": "T2",
        "availability": "DOWNLOAD",
        "licence": "Other (Public Domain) as stated by the OpenCity portal",
        "attribution": "BBMP flooding locations, via OpenCity Urban Data Portal",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_updated": "2025-11-27",
        "method": "http_download",
        "transformation": (
            "Three KML layers parsed to points; first vertex used where a "
            "placemark carries a line or polygon; duplicates removed at 5 dp"
        ),
        "access_notes": f"{len(features)} points, {len(paths)} layers, sha16={digest}",
        "max_confidence": 0.70,
        "verification_status": "PARTIAL_COVERAGE",
        "caveats": [
            NOT_A_HAZARD_MODEL,
            ABSENCE_MEANS_NOTHING,
            "POINT DATA, NOT INUNDATION GEOMETRY. A point marks a reported "
            "location, not the extent of flooding around it.",
            "No date is attached per point, so the reporting period is unknown "
            "and conditions may have changed since.",
            "This layer does NOT feed the environmental risk score. Flood "
            "remains listed as excluded there (audit R7).",
        ],
        "coverage": {"city": "bengaluru", "points": len(features),
                     "kinds": kinds},
    }
    (OUT / "source_flood_locations_bengaluru.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8")

    print(f"\n  wrote {OUT / 'flood_locations_bengaluru.geojson'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
