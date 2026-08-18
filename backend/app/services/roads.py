"""Road intelligence — Module 8.

Nearest mapped road centreline, its hierarchy code and its published widths,
from the BBMP road width map.

WHAT THIS MODULE REFUSES TO DO
------------------------------
1. **It never returns a single "road width".** The source publishes an existing
   width and a proposed width that differ by roughly a factor of two. Both are
   returned under their own names, and the proposed one carries a caveat saying
   it must not drive a feasibility calculation.

2. **It never asserts that a road abuts a plot.** It returns the nearest mapped
   centreline and the distance to it. Which road legally abuts a property is a
   question about that property's boundary, which this project does not hold.

3. **It never guesses outside coverage.** The layer is BBMP-era. Beyond
   `MAX_ABUTMENT_M` from any mapped segment the answer is UNAVAILABLE.

Because of 1 and 2, nothing here is `VERIFIED`. The widths are `INDICATIVE`:
real published figures, attached to a road that may not be the one that matters.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.facts import Fact, SourceRef, Status, Tier

DATA = Path(__file__).resolve().parents[3] / "data" / "processed"
NETWORK = "road_network_bengaluru.geojson"
META = "source_road_network_bengaluru.json"

# Beyond this, the nearest centreline is not plausibly the abutting road.
MAX_ABUTMENT_M = 150.0

# ~0.005 deg is roughly 550 m at Bengaluru's latitude.
CELL = 0.005

WIDTH_CAVEAT = (
    "Published road width from the BBMP road width map, attached to the nearest "
    "mapped centreline. It is INDICATIVE: it is not a survey of the road "
    "abutting this plot, and which road legally abuts a property is determined "
    "by that property's boundary."
)

PROPOSED_CAVEAT = (
    "DO NOT USE FOR FEASIBILITY. This is read as a PROPOSED width — across the "
    "whole dataset it exceeds the existing width on every single segment, and "
    "the median is roughly double. Using it to compute FAR, height or setback "
    "would report floor area that is not permissible today."
)

HIERARCHY_CAVEAT = (
    "Road hierarchy codes are published without a data dictionary. Any "
    "expansion shown is an unverified interpretation, not source data."
)


@lru_cache(maxsize=2)
def _load(path_str: str, mtime: float) -> tuple[list, dict]:
    """Segments plus a grid index over their bounding boxes."""
    payload = json.loads(Path(path_str).read_text(encoding="utf-8"))
    segments: list[tuple[tuple, dict, list]] = []
    grid: dict[tuple[int, int], list[int]] = {}

    for f in payload.get("features", []):
        line = f["geometry"]["coordinates"]
        if len(line) < 2:
            continue
        xs = [p[0] for p in line]
        ys = [p[1] for p in line]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        idx = len(segments)
        segments.append((bbox, f["properties"], line))

        for cx in range(int(bbox[0] / CELL), int(bbox[2] / CELL) + 1):
            for cy in range(int(bbox[1] / CELL), int(bbox[3] / CELL) + 1):
                grid.setdefault((cx, cy), []).append(idx)

    return segments, grid


def _network() -> tuple[list, dict]:
    path = DATA / NETWORK
    if not path.exists():
        return [], {}
    return _load(str(path), path.stat().st_mtime)


def is_available() -> bool:
    return bool(_network()[0])


def _point_to_segment_m(lng: float, lat: float,
                        a: list[float], b: list[float]) -> float:
    """Distance from a point to a line segment, in metres.

    Equirectangular projection about the query point. Over the few hundred
    metres that matter here the distortion is far below the positional accuracy
    of the underlying centreline.
    """
    k = 111_320.0
    coslat = math.cos(math.radians(lat))
    px, py = 0.0, 0.0
    ax, ay = (a[0] - lng) * k * coslat, (a[1] - lat) * k
    bx, by = (b[0] - lng) * k * coslat, (b[1] - lat) * k

    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(ax, ay)

    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(ax + t * dx, ay + t * dy)


def nearest(lng: float, lat: float,
            max_distance_m: float = MAX_ABUTMENT_M) -> dict[str, Any] | None:
    """Nearest mapped road centreline, or None if nothing is close enough."""
    segments, grid = _network()
    if not segments:
        return None

    # Widen the cell search until it covers the distance being asked about.
    span = max(1, int(max_distance_m / (CELL * 111_320.0)) + 1)
    cx, cy = int(lng / CELL), int(lat / CELL)
    candidates: set[int] = set()
    for i in range(cx - span, cx + span + 1):
        for j in range(cy - span, cy + span + 1):
            candidates.update(grid.get((i, j), ()))

    best: tuple[float, dict] | None = None
    for idx in candidates:
        _bbox, props, line = segments[idx]
        d = min(_point_to_segment_m(lng, lat, line[i], line[i + 1])
                for i in range(len(line) - 1))
        if best is None or d < best[0]:
            best = (d, props)

    if best is None or best[0] > max_distance_m:
        return None

    distance, props = best
    return {"distance_m": round(distance, 1), **props}


@lru_cache(maxsize=1)
def coverage() -> dict[str, Any]:
    meta_path = DATA / META
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    segments, _grid = _network()
    cov = meta.get("coverage", {})
    return {
        "available": bool(segments),
        "segments": len(segments),
        "network_length_km": cov.get("network_length_km"),
        "hierarchy_codes": cov.get("hierarchy_codes", {}),
        "measured": cov.get("measured", {}),
        "partial": True,
        "note": (
            "Coverage is the former BBMP area, not all 369 Greater Bengaluru "
            "wards. A point more than "
            f"{MAX_ABUTMENT_M:.0f} m from any mapped centreline returns "
            "UNAVAILABLE rather than a distant road."
        ),
        "width_fields": {
            "width_existing_m": "Source field RR_width_B — read as existing width",
            "width_proposed_m": (
                "Source field RR_WIDTH_P — read as proposed width. "
                + PROPOSED_CAVEAT
            ),
        },
        "assumptions": meta.get("assumptions", []),
        "caveats": meta.get("caveats", []),
        "source_url": meta.get("source_url"),
        "licence": meta.get("licence"),
        "max_abutment_m": MAX_ABUTMENT_M,
    }


@lru_cache(maxsize=1)
def _source() -> SourceRef:
    meta_path = DATA / META
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, meta.get("source_url", "road-network")),
        name=meta.get("name", "Bengaluru road width map"),
        organisation=meta.get("organisation", "BBMP"),
        source_url=meta.get("source_url"),
        tier=Tier.T2,
        retrieved_at=(datetime.fromisoformat(meta["retrieved_at"])
                      if meta.get("retrieved_at") else None),
        source_updated=(date.fromisoformat(meta["source_updated"])
                        if meta.get("source_updated") else None),
        licence=meta.get("licence"),
    )


def facts(lng: float, lat: float, city_id: str = "bengaluru") -> dict[str, Fact[Any]]:
    """Road facts for a point, ready to merge into a jurisdiction answer."""
    keys = ("nearest_road_distance_m", "road_hierarchy_code",
            "road_width_existing_m", "road_width_proposed_m")

    if city_id != "bengaluru":
        reason = (
            "No road width layer has been ingested for this city. The BBMP road "
            "width map covers Bengaluru only."
        )
        return {k: Fact.unavailable(reason) for k in keys}

    if not is_available():
        reason = ("Road network not ingested. Run "
                  "etl/flows/ingest_road_network.py.")
        return {k: Fact.unavailable(reason) for k in keys}

    hit = nearest(lng, lat)
    if hit is None:
        reason = (
            f"No mapped road centreline within {MAX_ABUTMENT_M:.0f} m. Coverage "
            "is the former BBMP area; a more distant road is not reported, "
            "because it is not plausibly the abutting one."
        )
        return {k: Fact.unavailable(reason) for k in keys}

    src = _source()
    out: dict[str, Fact[Any]] = {}

    out["nearest_road_distance_m"] = Fact.observed(
        hit["distance_m"], source=src, confidence=0.80, status=Status.INDICATIVE,
        unit="m",
        caveats=["Distance to the nearest mapped centreline. It does not "
                 "establish that this road abuts the property."],
    )

    code = hit.get("hierarchy_code")
    if code:
        out["road_hierarchy_code"] = Fact.observed(
            code, source=src, confidence=0.80, status=Status.VERIFIED,
            caveats=[HIERARCHY_CAVEAT],
        )
    else:
        out["road_hierarchy_code"] = Fact.unavailable(
            "No hierarchy code on the matched segment")

    existing = hit.get("width_existing_m")
    out["road_width_existing_m"] = (
        Fact.observed(existing, source=src, confidence=0.75,
                      status=Status.INDICATIVE, unit="m", caveats=[WIDTH_CAVEAT])
        if existing else
        Fact.unavailable("No existing width published for the matched segment")
    )

    proposed = hit.get("width_proposed_m")
    out["road_width_proposed_m"] = (
        Fact.observed(proposed, source=src, confidence=0.75,
                      status=Status.INDICATIVE, unit="m",
                      caveats=[WIDTH_CAVEAT, PROPOSED_CAVEAT])
        if proposed else
        Fact.unavailable("No proposed width published for the matched segment")
    )

    return out


def feasibility_suggestion(lng: float, lat: float,
                           city_id: str = "bengaluru") -> dict[str, Any]:
    """A road width the user may adopt for feasibility — never adopted for them.

    Feasibility requires a user-declared road width carrying a source flag. This
    returns a candidate with the flag already set to `dataset`, which is a weaker
    provenance than `measured` or `official_document`, and says why.
    """
    if city_id != "bengaluru" or not is_available():
        return {
            "available": False,
            "reason": "No road width layer for this city.",
        }

    hit = nearest(lng, lat)
    if hit is None or not hit.get("width_existing_m"):
        return {
            "available": False,
            "reason": (
                f"No mapped road centreline with a published width within "
                f"{MAX_ABUTMENT_M:.0f} m."
            ),
        }

    return {
        "available": True,
        "suggested_road_width_m": hit["width_existing_m"],
        "source_flag": "dataset",
        "distance_to_centreline_m": hit["distance_m"],
        "hierarchy_code": hit.get("hierarchy_code"),
        "not_used_automatically": (
            "This is offered, not applied. Feasibility still requires you to "
            "declare a road width and its provenance, and a result derived from "
            "a dataset width is weaker than one derived from a sanctioned plan."
        ),
        "excluded": {
            "width_proposed_m": hit.get("width_proposed_m"),
            "why": PROPOSED_CAVEAT,
        },
        "caveat": WIDTH_CAVEAT,
    }
