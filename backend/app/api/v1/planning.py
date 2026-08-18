"""Module 21 — Government / Urban Planning dashboard API.

Serves the ward-level aggregates written by ml/pipelines/ward_analytics.py.

Everything here is a DATA-DRIVEN SCORE. It is decision-support for exploration,
not an official planning instrument, and the response says so.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query

from app.core.disclaimers import PLATFORM_NATURE
from app.core.problems import DataUnavailable
from app.services import cities

router = APIRouter()

DATA = Path(__file__).resolve().parents[4] / "data" / "processed"

METRICS = {
    "infrastructure_score": "Overall infrastructure access (0-100)",
    "development_pressure": "Market activity relative to infrastructure",
    "median_psf": "Median price per sq.ft",
    "facility_density_per_km2": "Facilities per square kilometre",
    "facilities_total": "Total mapped facilities in the ward",
}


@lru_cache(maxsize=4)
def _load(city: str, mtime: float) -> dict[str, Any]:
    return json.loads((DATA / f"ward_analytics_{city}.json").read_text(encoding="utf-8"))


def _analytics(city: str) -> dict[str, Any]:
    path = DATA / f"ward_analytics_{city}.json"
    if not path.exists():
        raise DataUnavailable(
            f"No ward analytics for {city}. Run "
            f"`python ml/pipelines/ward_analytics.py {city}`.",
            city=city,
        )
    return _load(city, path.stat().st_mtime)


@router.get("/summary", summary="Ward-level planning summary")
async def summary(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    d = _analytics(c.id)
    return {
        "city": {"id": c.id, "name": c.name, "authority": c.authority},
        "method": d.get("method"),
        "ward_count": d.get("ward_count"),
        "summary": d.get("summary", {}),
        "coverage": d.get("coverage", {}),
        "service_groups": d.get("service_groups", {}),
        "reach_metres": d.get("reach_metres", {}),
        "rankings": d.get("rankings", {}),
        "available_metrics": METRICS,
        "caveats": d.get("caveats", []),
        "generated_at": d.get("generated_at"),
        "disclaimers": [PLATFORM_NATURE],
    }


@router.get("/wards", summary="All wards with their analytics")
async def wards(
    city: str = Query("bengaluru"),
    metric: str = Query("infrastructure_score"),
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(400, ge=1, le=500),
) -> dict[str, Any]:
    c = cities.get(city)
    d = _analytics(c.id)
    if metric not in METRICS:
        raise DataUnavailable(f"Unknown metric {metric!r}", available=list(METRICS))

    rows = [r for r in d["wards"] if r.get(metric) is not None]
    rows.sort(key=lambda r: r[metric], reverse=(order == "desc"))
    missing = len(d["wards"]) - len(rows)

    return {
        "city": {"id": c.id, "name": c.name},
        "metric": metric,
        "metric_label": METRICS[metric],
        "order": order,
        "returned": len(rows[:limit]),
        "wards_without_this_metric": missing,
        "note": (
            f"{missing} ward(s) have no value for this metric and are omitted "
            "rather than shown as zero."
        ) if missing else None,
        "data": rows[:limit],
        "coverage": d.get("coverage", {}),
    }


@router.get("/choropleth", summary="Ward values keyed for map shading")
async def choropleth(
    city: str = Query("bengaluru"),
    metric: str = Query("infrastructure_score"),
) -> dict[str, Any]:
    """Compact {ward_no: value} map plus the range, for colouring the map."""
    c = cities.get(city)
    d = _analytics(c.id)
    if metric not in METRICS:
        raise DataUnavailable(f"Unknown metric {metric!r}", available=list(METRICS))

    # Keyed by "corporation|ward_no": ward numbers repeat across corporations,
    # so a number-only key would shade five different wards identically.
    values = {
        r["ward_key"]: r[metric]
        for r in d["wards"]
        if r.get(metric) is not None and r.get("ward_key")
    }
    nums = list(values.values())
    return {
        "city": c.id,
        "metric": metric,
        "metric_label": METRICS[metric],
        "values": values,
        "min": min(nums) if nums else None,
        "max": max(nums) if nums else None,
        "key_format": "corporation|ward_no",
        "count": len(values),
        "missing": d.get("ward_count", 0) - len(values),
        "coverage": d.get("coverage", {}),
    }
