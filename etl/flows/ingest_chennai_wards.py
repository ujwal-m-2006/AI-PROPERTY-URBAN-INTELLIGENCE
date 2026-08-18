"""Chennai GIS ingest — Greater Chennai Corporation wards and zones.

Source: GCC Ward Map 2022 + GCC Zones Map 2022, via the OpenCity urban data
portal.

Mirrors etl/flows/ingest_gba_wards.py in structure and validation strictness.
That file is NOT modified — Bengaluru's pipeline stays exactly as it was.

One difference in the source data: the GCC ward KML carries only a ward number,
with no zone attribute. Zone, zone name and region are therefore assigned by a
point-in-polygon spatial join of each ward's centroid against the zones layer.
That assignment is DERIVED and is labelled as such on every ward.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, date
from pathlib import Path
from typing import Any

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

SOURCE_URL = "https://data.opencity.in/dataset/gcc-ward-information"
EXPECTED_WARDS = 200


# --- parsing (same approach as the GBA flow) -----------------------------


def _simple_data(placemark: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for sd in placemark.iterfind(".//kml:SimpleData", KML_NS):
        name = sd.get("name")
        if name:
            out[name.strip()] = (sd.text or "").strip()
    return out


def _placemark_name(placemark: ET.Element) -> str:
    node = placemark.find("kml:name", KML_NS)
    return (node.text or "").strip() if node is not None else ""


def _ring(coord_text: str) -> list[list[float]]:
    ring: list[list[float]] = []
    for token in coord_text.split():
        parts = token.split(",")
        if len(parts) >= 2:
            try:
                ring.append([round(float(parts[0]), 7), round(float(parts[1]), 7)])
            except ValueError:
                continue
    return ring


def _polygons(placemark: ET.Element) -> list[list[list[list[float]]]]:
    polys = []
    for poly in placemark.iterfind(".//kml:Polygon", KML_NS):
        rings = []
        outer = poly.find(".//kml:outerBoundaryIs//kml:coordinates", KML_NS)
        if outer is None or not outer.text:
            continue
        ring = _ring(outer.text)
        if len(ring) < 4:
            continue
        rings.append(ring)
        for inner in poly.iterfind(".//kml:innerBoundaryIs//kml:coordinates", KML_NS):
            if inner.text:
                hole = _ring(inner.text)
                if len(hole) >= 4:
                    rings.append(hole)
        polys.append(rings)
    return polys


def _int_or_none(value: str) -> int | None:
    v = re.sub(r"[^\d]", "", value or "")
    return int(v) if v else None


# --- geometry helpers ----------------------------------------------------


def centroid(polys: list) -> tuple[float, float] | None:
    best, best_len = None, -1
    for poly in polys:
        ring = poly[0] if poly else None
        if ring and len(ring) > best_len:
            best, best_len = ring, len(ring)
    if not best:
        return None
    return (
        sum(p[0] for p in best) / len(best),
        sum(p[1] for p in best) / len(best),
    )


def _in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def _in_polygon(lon: float, lat: float, rings: list) -> bool:
    if not rings or not _in_ring(lon, lat, rings[0]):
        return False
    return not any(_in_ring(lon, lat, hole) for hole in rings[1:])


# --- loaders -------------------------------------------------------------


def parse_zones(path: Path) -> list[dict[str, Any]]:
    tree = ET.parse(path)
    zones = []
    for pm in tree.iterfind(".//kml:Placemark", KML_NS):
        attrs = _simple_data(pm)
        polys = _polygons(pm)
        if not polys:
            continue
        zones.append(
            {
                "type": "Feature",
                "properties": {
                    "zone": attrs.get("ZONE") or None,
                    "zone_name": attrs.get("ZONE_NAME") or _placemark_name(pm) or None,
                    "region": attrs.get("Region") or None,
                },
                "geometry": (
                    {"type": "Polygon", "coordinates": polys[0]}
                    if len(polys) == 1
                    else {"type": "MultiPolygon", "coordinates": polys}
                ),
                "_polys": polys,
            }
        )
    return zones


def load_localities() -> list[dict[str, Any]]:
    """OSM place names for Chennai, used to give each ward a human place name.

    The GCC ward source publishes numbers only. Rather than leave 200 wards
    labelled "Ward 137", each ward is matched to the OpenStreetMap locality
    whose centre lies inside it (or the nearest one). The result is DERIVED and
    is labelled as such — it is a helpful place name, not an official ward name.
    """
    path = OUT / "locality_gazetteer_chennai.json"
    if not path.exists():
        return []
    places = json.loads(path.read_text(encoding="utf-8")).get("places", [])
    rank = {"suburb": 0, "neighbourhood": 1, "quarter": 2, "town": 3,
            "village": 4, "locality": 5, "hamlet": 6}
    places.sort(key=lambda p: rank.get(p.get("place_type") or "", 9))
    return places


def _place_for_ward(polys: list, centre: tuple[float, float] | None,
                    places: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The matched locality, not just its English name.

    This used to return `p["name"]` and throw the rest away — including
    `name_local`, the Tamil name OpenStreetMap already carries. Bengaluru's
    wards all show a Kannada name and Chennai's showed none, purely because the
    field was discarded here.
    """
    if not places:
        return None
    # Places whose centre falls inside the ward, in rank order.
    inside = [p for p in places
              if any(_in_polygon(p["lng"], p["lat"], poly) for poly in polys)]
    if inside:
        # Among equally valid containing localities, prefer one that carries a
        # Tamil name — the English and Tamil labels must describe the SAME
        # place, so this is a choice between candidates, never a mix of two.
        with_local = [p for p in inside if p.get("name_local")]
        return (with_local or inside)[0]
    # Otherwise the closest place centre to the ward centre.
    if centre is None:
        return None
    best, best_d = None, float("inf")
    for p in places:
        d = (p["lng"] - centre[0]) ** 2 + (p["lat"] - centre[1]) ** 2
        if d < best_d:
            best, best_d = p, d
    # ~0.02 degrees is roughly 2 km; beyond that the label is not meaningful.
    return best if best and best_d <= 0.0004 else None


def parse_wards(path: Path, zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tree = ET.parse(path)
    features: list[dict[str, Any]] = []
    places = load_localities()
    used: dict[str, int] = {}

    for pm in tree.iterfind(".//kml:Placemark", KML_NS):
        attrs = _simple_data(pm)
        ward_no = _int_or_none(attrs.get("name") or _placemark_name(pm))
        polys = _polygons(pm)
        if not polys or ward_no is None:
            continue

        # Zone is not in the ward file — derive it spatially.
        zone = zone_name = region = None
        c = centroid(polys)
        if c:
            for z in zones:
                if any(_in_polygon(c[0], c[1], p) for p in z["_polys"]):
                    zone = z["properties"]["zone"]
                    zone_name = z["properties"]["zone_name"]
                    region = z["properties"]["region"]
                    break

        matched = _place_for_ward(polys, c, places)
        place = matched["name"] if matched else None
        # OSM carries a Tamil name for many but not all localities. Where it is
        # absent the field stays null rather than being transliterated — a
        # machine-made Tamil spelling of an English name is not a Tamil name.
        place_local = (matched or {}).get("name_local") or None
        if place:
            used[place] = used.get(place, 0) + 1
        ward_name = f"Ward {ward_no} - {place}" if place else f"Ward {ward_no}"
        ward_name_local = (f"வார்டு {ward_no} - {place_local}"
                           if place_local else None)

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "ward_no": ward_no,
                    "ward_name": ward_name,
                    "place_name": place,
                    "place_name_local": place_local,
                    "place_name_source": (
                        "DERIVED - nearest/containing OpenStreetMap locality; "
                        "not an official ward name"
                    ),
                    # `ward_name_kn` is the generic local-language slot the UI
                    # reads for both cities; the suffix is historical. The
                    # explicit pair below says which language it actually is.
                    "ward_name_kn": ward_name_local,
                    "ward_name_local": ward_name_local,
                    "ward_name_local_lang": "ta" if ward_name_local else None,
                    "ward_name_local_source": (
                        "DERIVED - Tamil name of the matched OpenStreetMap "
                        "locality. Not an official GCC ward name in Tamil."
                        if ward_name_local else None
                    ),
                    "corporation": "Greater Chennai Corporation",
                    # GCC's own official Tamil name, as the corporation itself
                    # publishes it. Not derived and not transliterated.
                    "corporation_kn": "பெருநகர சென்னை மாநகராட்சி",
                    "zone": (zone_name.title()
                             if zone_name and zone_name.isupper() else zone_name),
                    "zone_code": zone,
                    "region": region,
                    "zone_source": "DERIVED — centroid-in-polygon join to GCC zones 2022",
                    "division": None,
                    "sub_division": None,
                    "assembly": None,
                    "population_total": None,
                    "population_status": "UNAVAILABLE",
                },
                "geometry": (
                    {"type": "Polygon", "coordinates": polys[0]}
                    if len(polys) == 1
                    else {"type": "MultiPolygon", "coordinates": polys}
                ),
            }
        )
    return features


# --- validation ----------------------------------------------------------


def validate(features: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []

    if len(features) != EXPECTED_WARDS:
        problems.append(f"expected {EXPECTED_WARDS} wards, parsed {len(features)}")

    nos = [f["properties"]["ward_no"] for f in features]
    if len(set(nos)) != len(nos):
        dupes = sorted({n for n in nos if nos.count(n) > 1})
        problems.append(f"duplicate ward numbers: {dupes[:10]}")

    for f in features:
        for ring in _iter_rings(f["geometry"]):
            if ring[0] != ring[-1]:
                problems.append(f"ward {f['properties']['ward_no']}: unclosed ring")
                break

    # Chennai bounding box sanity.
    for f in features:
        bad = False
        for ring in _iter_rings(f["geometry"]):
            for lon, lat in ring:
                if not (79.9 < lon < 80.5 and 12.7 < lat < 13.4):
                    problems.append(
                        f"ward {f['properties']['ward_no']}: vertex outside "
                        f"Chennai bbox ({lon}, {lat})"
                    )
                    bad = True
                    break
            if bad:
                break

    return problems


def _iter_rings(geometry: dict[str, Any]):
    if geometry["type"] == "Polygon":
        yield from geometry["coordinates"]
    else:
        for poly in geometry["coordinates"]:
            yield from poly


# --- entry point ---------------------------------------------------------


def main() -> int:
    ward_kml = RAW / "chennai_gcc_wards_2022.kml"
    zone_kml = RAW / "chennai_gcc_zones_2022.kml"

    if not ward_kml.exists():
        print(f"missing {ward_kml}")
        return 1

    print("parsing GCC zones ...")
    zones = parse_zones(zone_kml) if zone_kml.exists() else []
    print(f"  {len(zones)} zone polygons")

    print("parsing GCC wards ...")
    wards = parse_wards(ward_kml, zones)
    print(f"  parsed {len(wards)} wards")

    problems = validate(wards)
    if problems:
        print("\nVALIDATION FAILED — refusing to write output:")
        for p in problems[:15]:
            print(f"  - {p}")
        return 2
    print("  validation passed")

    matched = sum(1 for w in wards if w["properties"]["zone"])
    named = sum(1 for w in wards if w["properties"].get("place_name"))
    print(f"  {matched}/{len(wards)} wards matched to a zone by spatial join")
    localised = sum(1 for w in wards if w["properties"].get("ward_name_local"))
    print(f"  {named}/{len(wards)} wards given a place name from OSM localities")
    print(f"  {localised}/{len(wards)} wards given a TAMIL name "
          f"({localised / len(wards):.0%}) — OSM does not carry name:ta for "
          "every locality, and no name is transliterated to fill the gap")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chennai_wards.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": wards}), encoding="utf-8"
    )
    for z in zones:
        z.pop("_polys", None)
    (OUT / "chennai_zones.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": zones}), encoding="utf-8"
    )

    digest = hashlib.sha256(ward_kml.read_bytes()).hexdigest()
    provenance = {
        "name": "Greater Chennai Corporation ward and zone boundaries (2022)",
        "organisation": "Greater Chennai Corporation",
        "source_url": SOURCE_URL,
        "dataset_name": "gcc-ward-information",
        "tier": "T2",
        "availability": "DOWNLOAD",
        "licence": "As published by the OpenCity urban data portal",
        "attribution": "Greater Chennai Corporation, via OpenCity Urban Data Portal",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_updated": date(2022, 1, 1).isoformat(),
        "method": "http_download",
        "transformation": (
            "KML parsed to GeoJSON; ward count and ring closure validated; "
            "zone/region assigned by centroid-in-polygon join against the GCC "
            "zones layer (DERIVED)"
        ),
        "access_notes": f"sha256={digest}; {len(wards)} wards; {len(zones)} zones",
        "max_confidence": 0.85,
        "verification_status": "VERIFIED_COUNTS",
        "caveats": [
            "Ward names are not published in this source — wards are identified "
            "by number only",
            "Zone assignment is derived by spatial join, not read from the "
            "ward source file",
            "Ward map vintage is 2022; re-check for later delimitation",
        ],
    }
    (OUT / "source_chennai_wards.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )

    by_zone: dict[str, int] = {}
    for w in wards:
        by_zone[w["properties"]["zone"] or "(unmatched)"] = (
            by_zone.get(w["properties"]["zone"] or "(unmatched)", 0) + 1
        )
    print("\nwards per zone:")
    for zname, n in sorted(by_zone.items(), key=lambda kv: -kv[1]):
        print(f"  {zname:<22} {n:>3}")

    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
