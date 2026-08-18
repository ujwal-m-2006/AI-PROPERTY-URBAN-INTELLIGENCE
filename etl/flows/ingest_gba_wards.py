"""Phase 2 — ingest the GBA 369-ward final delimitation.

Source: Greater Bengaluru Authority, via the OpenCity urban data portal.
        Final delimitation notified 19 November 2025.

Produces normalised GeoJSON plus a dissolved corporation layer, and writes the
provenance record that every downstream fact will point back to.

Stdlib only, deliberately: this must run on a bare machine during a demo without
a GeoPandas/GDAL install standing between you and a working map.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

SOURCE_URL = (
    "https://data.opencity.in/dataset/gba-wards-delimitation-2025"
)
KML_URL = (
    "https://data.opencity.in/dataset/863209cb-4ced-4f51-b5c5-156939c50922/"
    "resource/9013d656-8051-4e2d-9648-46efd0d86d3d/download/"
    "gba-369-wards-december-2025.kml"
)

EXPECTED_WARDS = 369
EXPECTED_CORPORATIONS = {"North", "South", "East", "West", "Central"}


# --- parsing -------------------------------------------------------------


def _simple_data(placemark: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for sd in placemark.iterfind(".//kml:SimpleData", KML_NS):
        name = sd.get("name")
        if name:
            out[name.strip()] = (sd.text or "").strip()
    return out


def _ring(coord_text: str) -> list[list[float]]:
    """KML coordinates are 'lon,lat[,alt] lon,lat[,alt] ...'."""
    ring: list[list[float]] = []
    for token in coord_text.split():
        parts = token.split(",")
        if len(parts) >= 2:
            ring.append([round(float(parts[0]), 7), round(float(parts[1]), 7)])
    return ring


def _polygons(placemark: ET.Element) -> list[list[list[list[float]]]]:
    """Every Polygon in this placemark, as [outer_ring, *inner_rings]."""
    polys = []
    for poly in placemark.iterfind(".//kml:Polygon", KML_NS):
        rings = []
        outer = poly.find(".//kml:outerBoundaryIs//kml:coordinates", KML_NS)
        if outer is None or not outer.text:
            continue
        rings.append(_ring(outer.text))
        for inner in poly.iterfind(".//kml:innerBoundaryIs//kml:coordinates", KML_NS):
            if inner.text:
                rings.append(_ring(inner.text))
        polys.append(rings)
    return polys


def _int_or_none(value: str) -> int | None:
    v = re.sub(r"[^\d-]", "", value or "")
    return int(v) if v and v != "-" else None


def _normalise(attrs: dict[str, str]) -> dict[str, Any]:
    """Map the source's field names onto our schema.

    Kannada names are carried through: a Bengaluru civic tool that cannot show
    a ward name in Kannada is not finished.
    """
    ward_no = _int_or_none(attrs.get("ward_id", ""))
    return {
        "ward_no": ward_no,
        "ward_name": attrs.get("Ward_Name") or attrs.get("ward_name") or None,
        "ward_name_kn": attrs.get("ward_name_kn") or None,
        "corporation": attrs.get("Corporation") or None,
        "corporation_kn": attrs.get("corporation_kn") or None,
        "corporation_id": attrs.get("corporation_id") or None,
        "zone": attrs.get("zone_name") or attrs.get("zone") or None,
        "division": attrs.get("RO_Division") or None,
        "sub_division": attrs.get("ARO_ Sub Division") or attrs.get("ARO_Sub Division") or None,
        "assembly": attrs.get("Assembly") or attrs.get("ac") or None,
        "assembly_no": _int_or_none(attrs.get("ac_no", "")),
        # The TOT_P/TOT_M/TOT_F fields do not behave like ward populations:
        # they sum to ~84 million across the 369 wards against a Greater
        # Bengaluru figure of roughly 14 million, i.e. about 6x too large, and
        # they are not constant within an assembly constituency either. Until
        # the field definition is confirmed against the source notification we
        # carry the raw numbers under names that assert nothing, and publish
        # no population figure at all. See audit task R9.
        "population_total": None,
        "population_status": "UNVERIFIED",
        "population_note": (
            "Source TOT_P field sums to ~6x the known Greater Bengaluru "
            "population; field definition unconfirmed. Not published."
        ),
        "_raw_tot_p": _int_or_none(attrs.get("TOT_P", "")),
        "_raw_tot_m": _int_or_none(attrs.get("TOT_M", "")),
        "_raw_tot_f": _int_or_none(attrs.get("TOT_F", "")),
        "_raw_sc_p": _int_or_none(attrs.get("SC_P", "")),
        "_raw_st_p": _int_or_none(attrs.get("ST_P", "")),
    }


def parse_wards(kml_path: Path) -> list[dict[str, Any]]:
    tree = ET.parse(kml_path)
    features: list[dict[str, Any]] = []

    for placemark in tree.iterfind(".//kml:Placemark", KML_NS):
        props = _normalise(_simple_data(placemark))
        polys = _polygons(placemark)
        if not polys:
            continue

        geometry: dict[str, Any] = (
            {"type": "Polygon", "coordinates": polys[0]}
            if len(polys) == 1
            else {"type": "MultiPolygon", "coordinates": polys}
        )
        features.append(
            {"type": "Feature", "properties": props, "geometry": geometry}
        )

    return features


# --- validation ----------------------------------------------------------


def validate(features: list[dict[str, Any]]) -> list[str]:
    """Fail loudly on anything that would silently corrupt jurisdiction answers."""
    problems: list[str] = []

    if len(features) != EXPECTED_WARDS:
        problems.append(f"expected {EXPECTED_WARDS} wards, parsed {len(features)}")

    # Ward numbers restart at 1 within each corporation, so the identity of a
    # ward is (corporation, ward_no). Anything keyed on ward_no alone would
    # silently merge five different wards — exactly the class of bug that makes
    # a jurisdiction answer confidently wrong.
    keys = [(f["properties"]["corporation"], f["properties"]["ward_no"]) for f in features]
    if len(set(keys)) != len(keys):
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        problems.append(f"duplicate (corporation, ward_no) keys: {dupes[:10]}")
    if any(n is None for _, n in keys):
        problems.append("some wards have no ward number")

    corps = {f["properties"]["corporation"] for f in features}
    if corps != EXPECTED_CORPORATIONS:
        problems.append(f"unexpected corporations: {sorted(c or '?' for c in corps)}")

    for f in features:
        for ring in _iter_rings(f["geometry"]):
            if len(ring) < 4:
                problems.append(f"ward {f['properties']['ward_no']}: degenerate ring")
            elif ring[0] != ring[-1]:
                problems.append(f"ward {f['properties']['ward_no']}: unclosed ring")

    # Every vertex must land inside a generous Bengaluru bounding box.
    for f in features:
        for ring in _iter_rings(f["geometry"]):
            for lon, lat in ring:
                if not (77.0 < lon < 78.2 and 12.5 < lat < 13.5):
                    problems.append(
                        f"ward {f['properties']['ward_no']}: vertex outside "
                        f"Bengaluru bbox ({lon}, {lat})"
                    )
                    break
            else:
                continue
            break

    return problems


def _iter_rings(geometry: dict[str, Any]):
    if geometry["type"] == "Polygon":
        yield from geometry["coordinates"]
    else:
        for poly in geometry["coordinates"]:
            yield from poly


# --- derived layers ------------------------------------------------------


def dissolve_corporations(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group ward polygons by corporation.

    A true topological dissolve needs a geometry engine; this collects member
    polygons into a MultiPolygon, which is what the map and point-in-polygon
    lookup actually need. Shared internal edges remain — cosmetic only, and
    noted here so nobody mistakes it for a cleaned boundary.
    """
    by_corp: dict[str, list[Any]] = {}
    stats: dict[str, dict[str, int]] = {}

    for f in features:
        corp = f["properties"]["corporation"]
        if not corp:
            continue
        polys = (
            [f["geometry"]["coordinates"]]
            if f["geometry"]["type"] == "Polygon"
            else list(f["geometry"]["coordinates"])
        )
        by_corp.setdefault(corp, []).extend(polys)
        s = stats.setdefault(corp, {"wards": 0})
        s["wards"] += 1

    return [
        {
            "type": "Feature",
            "properties": {
                "corporation": corp,
                "ward_count": stats[corp]["wards"],
                "population_total": None,
                "population_status": "UNVERIFIED",
                "is_derived": True,
                "derivation": "union of member ward polygons (edges not cleaned)",
            },
            "geometry": {"type": "MultiPolygon", "coordinates": polys},
        }
        for corp, polys in sorted(by_corp.items())
    ]


def load_division_mapping(csv_path: Path) -> dict[int, dict[str, str]]:
    """The divisions CSV uses sparse (forward-filled) group columns."""
    if not csv_path.exists():
        return {}

    mapping: dict[int, dict[str, str]] = {}
    carry = {"Corporation": "", "Zone": "", "Division": "", "Sub-division": ""}

    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            for key in carry:
                if (row.get(key) or "").strip():
                    carry[key] = row[key].strip()
            ward_no = _int_or_none(row.get("Ward no", ""))
            if ward_no is not None:
                mapping[ward_no] = dict(carry)
    return mapping


# --- provenance ----------------------------------------------------------


def provenance(kml_path: Path, feature_count: int) -> dict[str, Any]:
    digest = hashlib.sha256(kml_path.read_bytes()).hexdigest()
    return {
        "name": "GBA Final Wards Delimitation 2025 (369 wards, with population)",
        "organisation": "Greater Bengaluru Authority",
        "source_url": SOURCE_URL,
        "download_url": KML_URL,
        "dataset_name": "gba-wards-delimitation-2025",
        "tier": "T2",
        "availability": "DOWNLOAD",
        "licence": "Other (Public Domain) as stated by the OpenCity portal",
        "attribution": "Greater Bengaluru Authority, via OpenCity Urban Data Portal",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_updated": date(2025, 12, 1).isoformat(),
        "method": "http_download",
        "transformation": (
            "KML parsed to GeoJSON; field names normalised; ward/corporation "
            "counts and ring closure validated; corporations derived by grouping "
            "ward polygons"
        ),
        "access_notes": f"sha256={digest}; {feature_count} features parsed",
        "max_confidence": 0.85,
        "verification_status": "VERIFIED_COUNTS",
        "notes": (
            "Final delimitation notified 19 Nov 2025. Boundaries are temporal — "
            "re-check quarterly. Corporation layer is derived (is_derived=true)."
        ),
    }


# --- entry point ---------------------------------------------------------


def main() -> int:
    kml = RAW / "gba-369-wards-december-2025.kml"
    if not kml.exists():
        print(f"missing {kml}\ndownload it from {KML_URL}")
        return 1

    print(f"parsing {kml.name} ...")
    wards = parse_wards(kml)
    print(f"  parsed {len(wards)} wards")

    problems = validate(wards)
    if problems:
        print("\nVALIDATION FAILED — refusing to write output:")
        for p in problems[:20]:
            print(f"  - {p}")
        return 2
    print("  validation passed")

    divisions = load_division_mapping(RAW / "gba-wards-divisions-mapping.csv")
    if divisions:
        filled = 0
        for f in wards:
            extra = divisions.get(f["properties"]["ward_no"])
            if extra:
                f["properties"].setdefault("zone_csv", extra["Zone"])
                if not f["properties"]["division"]:
                    f["properties"]["division"] = extra["Division"]
                if not f["properties"]["sub_division"]:
                    f["properties"]["sub_division"] = extra["Sub-division"]
                filled += 1
        print(f"  enriched {filled} wards from the divisions CSV")

    corporations = dissolve_corporations(wards)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gba_wards.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": wards}), encoding="utf-8"
    )
    (OUT / "gba_corporations.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": corporations}),
        encoding="utf-8",
    )
    (OUT / "source_gba_wards.json").write_text(
        json.dumps(provenance(kml, len(wards)), indent=2), encoding="utf-8"
    )

    print("\ncorporations:")
    for c in corporations:
        p = c["properties"]
        print(f"  {p['corporation']:<8} {p['ward_count']:>3} wards")
    print(f"  {'TOTAL':<8} {len(wards):>3} wards")
    print(
        "\n  note: ward population is NOT published — the source TOT_P field "
        "sums to ~6x\n  the known Greater Bengaluru population and its "
        "definition is unconfirmed (R9)."
    )
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
