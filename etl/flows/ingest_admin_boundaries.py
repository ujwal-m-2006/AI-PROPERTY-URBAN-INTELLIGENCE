"""District and taluk boundaries for BOTH cities — complete areal coverage.

WHY THIS EXISTS
---------------
The revenue-sheet ingest (`ingest_revenue_maps.py`) gives taluk, hobli, village
and survey number — but only where cadastral sheets are published. That is 3
taluks and 7 hoblis of Bengaluru, and nothing at all for Chennai. Outside that
footprint the platform correctly answered UNAVAILABLE, which is honest but
unhelpful for most of both cities.

Those are two different questions, and conflating them is what this module
avoids:

  * **"Which taluk is this point in?"** — an administrative boundary question,
    answerable everywhere from a polygon layer.
  * **"What is the survey number of this parcel?"** — a cadastral question,
    answerable only where a revenue sheet exists.

So this ingest fills the first for the whole of both cities. It does **not**
touch the second: survey number stays sourced from the revenue sheets, and
stays UNAVAILABLE outside them. A boundary layer cannot produce a survey number,
and nothing here pretends otherwise.

SOURCE AND ITS LIMITS
---------------------
`india-geodata`, a community compilation released CC0-1.0, carrying boundaries
derived from the **Local Government Directory (LGD)** and the **Survey of
India**. Both are official; the compilation is not, so this is T3, not T1.

Two limits travel with every value:

  * **Republished, not fetched from the issuing authority.** LGD and SOI are the
    upstream sources; this project retrieved a community mirror of them.
  * **Vintage is not stated per feature.** Karnataka and Tamil Nadu have both
    reorganised taluks in recent years. A taluk name here may predate a
    reorganisation, so it is reported as INDICATIVE, never VERIFIED.

    python etl/flows/ingest_admin_boundaries.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import py7zr

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "admin"
OUT = ROOT / "data" / "processed"

RELEASE = ("https://github.com/yashveeeeeeer/india-geodata/releases/download/"
           "admin/subdistricts/LGD_Subdistricts.geojsonl.7z")
SOURCE_PAGE = "https://github.com/yashveeeeeeer/india-geodata"

USER_AGENT = (
    "GBA-Property-Intelligence/0.1 (academic research prototype; "
    "contact via project README)"
)

# Generous bounding boxes — a subdistrict polygon is kept if it intersects.
CITY_BBOX = {
    "bengaluru": (77.20, 12.55, 78.05, 13.35),
    "chennai":   (79.95, 12.75, 80.45, 13.35),
}

# Field names vary across compilations; try several, take the first non-empty.
NAME_KEYS = ("subdistrict_name", "SUBDISTRICT_NAME", "sdtname", "SDTNAME",
             "tehsil", "TEHSIL", "name", "NAME", "taluk", "TALUK")
DISTRICT_KEYS = ("district_name", "DISTRICT_NAME", "dtname", "DTNAME",
                 "district", "DISTRICT")
STATE_KEYS = ("state_name", "STATE_NAME", "stname", "STNAME", "state", "STATE")


def _tidy(name: str) -> str:
    """Normalise casing only.

    The source mixes conventions — most names are title case but a few arrive
    ALL CAPS (e.g. YELAHANKA). Title-casing those makes the layer render
    consistently. Nothing else about the name is altered: no spelling is
    corrected, no name is mapped to another.
    """
    return name.title() if name.isupper() else name


def _first(props: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = props.get(k)
        if isinstance(v, str) and v.strip():
            return _tidy(v.strip())
    return None


def download() -> Path | None:
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / "LGD_Subdistricts.geojsonl.7z"
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"  cached: {dest.name} ({dest.stat().st_size / 1048576:.1f} MB)")
        return dest
    print(f"  downloading {RELEASE.rsplit('/', 1)[-1]} ...")
    try:
        with httpx.stream("GET", RELEASE, headers={"User-Agent": USER_AGENT},
                          timeout=600.0, follow_redirects=True) as r:
            r.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        print(f"  download failed: {type(exc).__name__}: {exc}")
        return None
    print(f"  {dest.stat().st_size / 1048576:.1f} MB")
    return dest


def extract(archive: Path) -> Path | None:
    work = RAW / "extracted"
    if work.exists():
        found = list(work.glob("*.geojsonl")) + list(work.glob("*.jsonl"))
        if found:
            print(f"  already extracted: {found[0].name}")
            return found[0]
    work.mkdir(parents=True, exist_ok=True)
    print("  extracting ...")
    with py7zr.SevenZipFile(archive, mode="r") as z:
        z.extractall(path=work)
    found = list(work.rglob("*.geojsonl")) + list(work.rglob("*.jsonl"))
    if not found:
        print("  no .geojsonl inside the archive")
        return None
    print(f"  {found[0].name} ({found[0].stat().st_size / 1048576:.1f} MB)")
    return found[0]


def _bounds(geom: dict[str, Any]) -> tuple[float, float, float, float] | None:
    t = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None
    if t == "Polygon":
        polys = [coords]
    elif t == "MultiPolygon":
        polys = coords
    else:
        return None
    xs, ys = [], []
    for poly in polys:
        for ring in poly:
            for pt in ring:
                xs.append(pt[0])
                ys.append(pt[1])
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _intersects(b: tuple[float, float, float, float],
                box: tuple[float, float, float, float]) -> bool:
    return not (b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3])


def _round(geom: dict[str, Any], nd: int = 5) -> dict[str, Any]:
    """Trim coordinate precision. 5 dp is ~1 m — far finer than the boundary."""
    def ring(r):
        return [[round(p[0], nd), round(p[1], nd)] for p in r]

    if geom["type"] == "Polygon":
        geom["coordinates"] = [ring(r) for r in geom["coordinates"]]
    else:
        geom["coordinates"] = [[ring(r) for r in poly]
                               for poly in geom["coordinates"]]
    return geom


def filter_cities(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Stream the national file, keeping only what touches the two cities."""
    kept: dict[str, list[dict[str, Any]]] = {c: [] for c in CITY_BBOX}
    seen = 0

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                feat = json.loads(line)
            except ValueError:
                continue
            geom = feat.get("geometry")
            if not geom:
                continue
            seen += 1
            b = _bounds(geom)
            if b is None:
                continue
            props = feat.get("properties", {}) or {}
            for city, box in CITY_BBOX.items():
                if not _intersects(b, box):
                    continue
                kept[city].append({
                    "type": "Feature",
                    "properties": {
                        "taluk": _first(props, NAME_KEYS),
                        "district": _first(props, DISTRICT_KEYS),
                        "state": _first(props, STATE_KEYS),
                    },
                    "geometry": _round(geom),
                })
            if seen % 2000 == 0:
                print(f"    scanned {seen:,} subdistricts ...", end="\r")

    print(f"    scanned {seen:,} subdistricts nationally      ")
    return kept


def validate(city: str, feats: list[dict[str, Any]]) -> list[str]:
    problems = []
    if not feats:
        problems.append(f"{city}: no subdistrict polygons intersect the bbox")
        return problems
    named = [f for f in feats if f["properties"]["taluk"]]
    if len(named) < len(feats) * 0.8:
        problems.append(
            f"{city}: only {len(named)}/{len(feats)} polygons carry a taluk name "
            "— the property key may differ in this release")
    districts = {f["properties"]["district"] for f in feats if f["properties"]["district"]}
    if not districts:
        problems.append(f"{city}: no district name on any polygon")
    return problems


def main() -> int:
    print("Administrative boundary ingest — district and taluk, both cities\n")

    archive = download()
    if archive is None:
        return 2
    path = extract(archive)
    if path is None:
        return 2

    print("\nfiltering to Bengaluru and Chennai ...")
    kept = filter_cities(path)

    problems: list[str] = []
    for city, feats in kept.items():
        problems.extend(validate(city, feats))
    if problems:
        print("\nVALIDATION FAILED — refusing to write output:")
        for p in problems[:10]:
            print(f"  - {p}")
        return 3

    OUT.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()[:16]

    for city, feats in kept.items():
        taluks = sorted({f["properties"]["taluk"] for f in feats
                         if f["properties"]["taluk"]})
        districts = sorted({f["properties"]["district"] for f in feats
                            if f["properties"]["district"]})
        print(f"\n  {city}")
        print(f"    polygons  : {len(feats)}")
        print(f"    districts : {', '.join(districts)}")
        print(f"    taluks    : {len(taluks)}")
        for t in taluks[:14]:
            print(f"                {t}")
        if len(taluks) > 14:
            print(f"                ... and {len(taluks) - 14} more")

        (OUT / f"admin_subdistricts_{city}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": feats}),
            encoding="utf-8")

        provenance = {
            "name": f"District and taluk boundaries — {city}",
            "organisation": ("Local Government Directory (LGD) and Survey of "
                             "India, via the india-geodata community compilation"),
            "source_url": SOURCE_PAGE,
            "download_url": RELEASE,
            "tier": "T3",
            "availability": "DOWNLOAD",
            "licence": "CC0-1.0 (public domain dedication, as released)",
            "attribution": "Boundaries from LGD / Survey of India via india-geodata (CC0)",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "source_updated": None,
            "method": "http_download",
            "transformation": (
                "National sub-district file streamed and filtered to each city's "
                "bounding box; coordinates rounded to 5 dp; ALL-CAPS names "
                "title-cased for consistent rendering (casing only — no name "
                "was corrected or remapped)"
            ),
            "access_notes": f"{len(feats)} polygons, {len(taluks)} taluks, sha16={digest}",
            "max_confidence": 0.70,
            "verification_status": "UNVERIFIED",
            "caveats": [
                "REPUBLISHED, NOT OFFICIAL. LGD and Survey of India are the "
                "upstream authorities; this project retrieved a community "
                "compilation of them, so it is T3 and reported as INDICATIVE.",
                "VINTAGE IS NOT STATED per feature. Karnataka and Tamil Nadu have "
                "both reorganised taluks in recent years, so a name here may "
                "predate a reorganisation.",
                "THIS LAYER CANNOT PRODUCE A SURVEY NUMBER. It answers which "
                "taluk a point falls in. Survey number remains sourced from the "
                "revenue sheets and stays UNAVAILABLE outside their footprint.",
                "Hobli is not an LGD level and is not present in this layer. It "
                "remains available only where a revenue sheet covers the point.",
            ],
            "coverage": {
                "city": city,
                "polygons": len(feats),
                "districts": districts,
                "taluks": taluks,
            },
        }
        (OUT / f"source_admin_subdistricts_{city}.json").write_text(
            json.dumps(provenance, indent=2), encoding="utf-8")

    # The extracted national file is large and no longer needed.
    shutil.rmtree(RAW / "extracted", ignore_errors=True)
    print(f"\n  wrote admin_subdistricts_*.geojson to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
