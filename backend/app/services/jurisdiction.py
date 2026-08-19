"""Phase 3 — jurisdiction lookup.

Answers "which corporation, zone, ward and administrative units does this point
fall under?" from the GBA 369-ward final delimitation.

Point-in-polygon runs in-process against the GeoJSON rather than in PostGIS.
That is a deliberate MVP trade: 369 polygons with a bounding-box prefilter
answer in well under a millisecond, and it means the demo runs without a
database. The PostGIS path (ST_Contains over a GiST index) is the production
target and the query is identical in shape.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple
from uuid import uuid5, NAMESPACE_URL

from app.core.problems import UnknownCity
from app.facts import Category, ConfidenceReport, Fact, SourceRef, Status, Tier, build_report

DATA = Path(__file__).resolve().parents[3] / "data" / "processed"

# Greater Bengaluru extent, used to distinguish "outside coverage" from
# "inside the area but in a gap between polygons" — different answers.
GBA_BBOX = (77.0, 12.5, 78.2, 13.5)


class WardHit(NamedTuple):
    properties: dict[str, Any]


CITY_SOURCE_FILE = {
    "bengaluru": "source_gba_wards.json",
    "chennai": "source_chennai_wards.json",
}


def _city_key(city: str | None) -> str:
    """Resolve a city id, refusing one we do not cover.

    Every lookup below is `DICT.get(city, <bengaluru default>)`, which turned an
    unknown city into Bengaluru's wards returned under the requested city's
    name — Bengaluru data labelled Mysuru. Refusing is the only honest answer.
    """
    key = (city or "bengaluru").strip().lower()
    if key not in CITY_WARDS_FILE:
        raise UnknownCity(
            f"unknown city {city!r}; available: "
            f"{', '.join(sorted(CITY_WARDS_FILE))}",
            available=sorted(CITY_WARDS_FILE),
        )
    return key


@lru_cache(maxsize=4)
def _source(city: str = "bengaluru") -> SourceRef:
    meta_path = DATA / CITY_SOURCE_FILE[_city_key(city)]
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, meta.get("source_url", f"{city}-wards")),
        name=meta.get("name", "GBA Final Wards Delimitation 2025"),
        organisation=meta.get("organisation", "Greater Bengaluru Authority"),
        source_url=meta.get("source_url"),
        tier=Tier.T2,
        retrieved_at=(
            datetime.fromisoformat(meta["retrieved_at"])
            if meta.get("retrieved_at")
            else None
        ),
        source_updated=(
            date.fromisoformat(meta["source_updated"])
            if meta.get("source_updated")
            else None
        ),
        licence=meta.get("licence"),
    )


CITY_WARDS_FILE = {
    "bengaluru": "gba_wards.geojson",
    "chennai": "chennai_wards.geojson",
}
CITY_BBOX = {
    "bengaluru": (77.0, 12.5, 78.2, 13.5),
    "chennai": (79.9, 12.7, 80.5, 13.4),
}


@lru_cache(maxsize=4)
def _wards(
    city: str = "bengaluru",
) -> list[tuple[tuple[float, float, float, float], dict[str, Any], Any]]:
    """Load a city's wards once, precomputing a bbox per ward for prefiltering."""
    path = DATA / CITY_WARDS_FILE[_city_key(city)]
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run the ward ingest flow for {city} first"
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for feature in payload["features"]:
        geom = feature["geometry"]
        polys = (
            [geom["coordinates"]]
            if geom["type"] == "Polygon"
            else geom["coordinates"]
        )
        xs = [pt[0] for poly in polys for ring in poly for pt in ring]
        ys = [pt[1] for poly in polys for ring in poly for pt in ring]
        out.append(((min(xs), min(ys), max(xs), max(ys)), feature["properties"], polys))
    return out


def _in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray casting. Standard crossing-number test."""
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


def _in_polygon(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    """Inside the outer ring and outside every hole."""
    if not rings or not _in_ring(lon, lat, rings[0]):
        return False
    return not any(_in_ring(lon, lat, hole) for hole in rings[1:])


def locate(lon: float, lat: float, city: str = "bengaluru") -> WardHit | None:
    for bbox, props, polys in _wards(city):
        minx, miny, maxx, maxy = bbox
        if not (minx <= lon <= maxx and miny <= lat <= maxy):
            continue
        if any(_in_polygon(lon, lat, poly) for poly in polys):
            return WardHit(properties=props)
    return None


def _centroid(polys: Any) -> tuple[float, float] | None:
    """Mean vertex of the largest ring — good enough to re-enter the ward."""
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


@lru_cache(maxsize=4)
def list_wards(city: str = "bengaluru") -> list[dict[str, Any]]:
    """All 369 wards with a representative point.

    Backs search and the ward picker, so a location can be selected without the
    map — the app must not be unusable if WebGL is unavailable.
    """
    out = []
    for _bbox, props, polys in _wards(city):
        centre = _centroid(polys)
        if centre is None:
            continue
        out.append(
            {
                "ward_no": props.get("ward_no"),
                "ward_name": props.get("ward_name"),
                "ward_name_kn": props.get("ward_name_kn"),
                "corporation": props.get("corporation"),
                "zone": props.get("zone"),
                "lng": round(centre[0], 6),
                "lat": round(centre[1], 6),
            }
        )
    return sorted(out, key=lambda w: (w["corporation"] or "", w["ward_no"] or 0))


def in_coverage(lon: float, lat: float, city: str = "bengaluru") -> bool:
    minx, miny, maxx, maxy = CITY_BBOX[_city_key(city)]
    return minx <= lon <= maxx and miny <= lat <= maxy


class JurisdictionResult(NamedTuple):
    facts: dict[str, Fact[Any]]
    confidence: ConfidenceReport
    found: bool


# Fields the source genuinely carries. Anything not in here is UNAVAILABLE with
# a reason, never blank-filled — see docs/01-data-source-audit.md.
_FIELD_MAP = {
    "corporation": ("corporation", "City corporation"),
    "corporation_kn": ("corporation_kn", "City corporation (Kannada)"),
    "ward_no": ("ward_no", "Ward number"),
    "ward_name": ("ward_name", "Ward name"),
    "ward_name_kn": ("ward_name_kn", "Ward name (Kannada)"),
    "zone": ("zone", "Zone"),
    "division": ("division", "Revenue division"),
    "sub_division": ("sub_division", "Sub-division"),
    "assembly": ("assembly", "Assembly constituency"),
}

# Requested in Module 1 but not present in any dataset we hold. Named
# explicitly so the UI shows a GREY row with a reason rather than nothing.
_KNOWN_GAPS = {
}

# District / taluk / hobli / village / survey number are supplied by the
# revenue-sheet layer where it has coverage. Chennai has no equivalent layer.
_REVENUE_KEYS = ("district", "taluk", "hobli", "village", "survey_number")


def jurisdiction(lon: float, lat: float, city: str = "bengaluru") -> JurisdictionResult:
    """Full Module 1 answer for a point, as Facts."""
    source = _source(city)
    facts: dict[str, Fact[Any]] = {}

    hit = locate(lon, lat, city)

    if hit is None:
        reason = (
            "Point is outside the Greater Bengaluru Authority area"
            if not in_coverage(lon, lat, city)
            else (
                "Point is within the Bengaluru region but does not fall inside "
                "any of the 369 GBA wards. It may lie under a separate authority "
                "(for example an industrial township such as ELCITA at Electronic "
                "City), or in a boundary gap. This is not resolved by guessing "
                "the nearest ward."
            )
        )
        for key in list(_FIELD_MAP) + list(_KNOWN_GAPS):
            facts[key] = Fact.unavailable(reason)
        from app.services import planning_authority

        facts.update(planning_authority.facts(city, inside_corporation=False))
        return JurisdictionResult(
            facts=facts,
            confidence=build_report({Category.JURISDICTION: facts}),
            found=False,
        )

    props = hit.properties
    for key, (src_key, _label) in _FIELD_MAP.items():
        value = props.get(src_key)
        if value in (None, ""):
            facts[key] = Fact.unavailable(f"Field '{src_key}' empty in source record")
        else:
            facts[key] = Fact.observed(
                value,
                source=source,
                confidence=0.85,
                status=Status.VERIFIED,
                valid_as_of=(
                date(2025, 11, 19) if city == "bengaluru" else date(2022, 1, 1)
            ),
            )

    for key, reason in _KNOWN_GAPS.items():
        facts[key] = Fact.unavailable(reason)

    # Revenue jurisdiction (cadastral, T2) where a sheet covers the point, then
    # the administrative boundary layer (areal, T3) for district and taluk
    # everywhere else. The boundary layer never supplies hobli, village or
    # survey number — it cannot know them.
    from app.services import admin_boundaries

    if city == "bengaluru":
        from app.services import revenue

        revenue_facts = revenue.facts(lon, lat)
    else:
        revenue_facts = {
            key: Fact.unavailable(
                f"No revenue-sheet layer has been ingested for {city}."
            )
            for key in _REVENUE_KEYS
        }

    facts.update(admin_boundaries.merge(revenue_facts, lon, lat, city))

    # Planning and building-permission authority. Inside corporation limits this
    # is fixed by statute rather than inferred from geography; outside them it
    # needs a boundary layer nobody publishes (audit R5).
    from app.services import planning_authority

    facts.update(planning_authority.facts(
        city, inside_corporation=True,
        corporation=props.get("corporation"),
    ))

    # Nearest mapped road. Never an assertion that this road abuts the plot.
    from app.services import roads

    facts.update(roads.facts(lon, lat, city_id=city))

    # Reported flooding locations (Module 12). Proximity only — this never
    # feeds the environmental risk score, which still lists flood as excluded.
    from app.services import flood

    facts.update(flood.facts(lon, lat, city_id=city))

    # Ward population is withheld in both cities, for different reasons. Both
    # are stated: a field that is simply absent from the response leaves the UI
    # with an empty section and the user with no explanation.
    if props.get("population_status") == "UNVERIFIED":
        facts["population"] = Fact.unavailable(
            "Source population field sums to ~6x the known Greater Bengaluru "
            "total, 125 of 369 wards fail male + female = total, and the cause "
            "is unexplained. Dividing by 6 would reproduce the published "
            "per-corporation averages, but a constant chosen to make a total "
            "look right is not provenance. No figure is published (audit R9)."
        )
    elif "population" not in facts:
        facts["population"] = Fact.unavailable(
            "The published ward layer for this city carries no population "
            "field, and ward-level population is not available from any other "
            "source held. No figure is estimated from city totals."
        )

    return JurisdictionResult(
        facts=facts,
        confidence=build_report({Category.JURISDICTION: facts}),
        found=True,
    )
