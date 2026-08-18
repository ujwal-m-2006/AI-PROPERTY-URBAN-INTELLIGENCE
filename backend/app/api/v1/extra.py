"""Endpoints for the additional models and market references.

Covers:
  * classification / clustering / anomaly artifacts (train_extra_models.py)
  * guidance value — manual reference entries, never scraped
  * transaction price — real for Chennai, unavailable for Bengaluru
  * revenue coverage — which taluks and hoblis are actually held
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.core.disclaimers import PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS
from app.core.problems import DataUnavailable
from app.services import cities, market_reference, revenue

router = APIRouter()

ARTIFACTS = Path(__file__).resolve().parents[4] / "ml" / "artifacts"


def _extra(city_id: str) -> dict[str, Any]:
    path = ARTIFACTS / city_id / "extra_models.json"
    if not path.exists():
        raise DataUnavailable(
            f"No additional models for {city_id}. Run "
            f"`python ml/pipelines/train_extra_models.py {city_id}`.",
            city=city_id,
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/models", summary="Classification, clustering and anomaly models")
async def extra_models(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    d = _extra(c.id)
    cl = d.get("classification", {})
    return {
        "city": {"id": c.id, "name": c.name},
        "classification": cl,
        "clustering": d.get("clustering", {}),
        "anomaly": d.get("anomaly", {}),
        "headline": (
            cl.get("warning")
            or f"Price-band classifier: accuracy {cl.get('accuracy')}, "
               f"macro F1 {cl.get('macro_f1')}, ROC-AUC {cl.get('roc_auc_ovr_macro')}"
        ),
        "model_families": {
            "regression": "price per sq.ft — the main model",
            "classification": "price band — supervised, multi-class",
            "clustering": "locality segmentation — unsupervised",
            "anomaly": "atypical records — unsupervised",
        },
        "generated_at": d.get("generated_at"),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }


# ------------------------------------------------------------ guidance value

class GuidanceEntry(BaseModel):
    city: str = "bengaluru"
    locality: str = Field(..., min_length=2, max_length=80)
    value_per_sqft: float = Field(..., gt=0, le=1_000_000)
    recorded_by: str = Field(..., min_length=2, max_length=80)
    notified_on: str | None = None


@router.get("/guidance-value", summary="Guidance value (manually recorded)")
async def guidance(city: str = Query("bengaluru"),
                   locality: str | None = Query(None)) -> dict[str, Any]:
    c = cities.get(city)
    result = market_reference.guidance_lookup(c.id, locality)
    result["city"] = {"id": c.id, "name": c.name}
    result["why_not_fetched"] = (
        "The official portal is the only source, has no public API, and its "
        "terms do not permit automated retrieval. The platform links to it and "
        "stores what a person records by hand, attributed to them."
    )
    return result


@router.post("/guidance-value", summary="Record a guidance value looked up by hand")
async def record_guidance(entry: GuidanceEntry) -> dict[str, Any]:
    c = cities.get(entry.city)
    saved = market_reference.record_guidance(
        city=c.id, locality=entry.locality,
        value_per_sqft=entry.value_per_sqft,
        recorded_by=entry.recorded_by, notified_on=entry.notified_on)
    return {
        "saved": saved,
        "method": market_reference.METHOD_MANUAL,
        "note": (
            "Stored as a MANUAL ENTRY with attribution. It is never labelled "
            "VERIFIED, because the platform did not retrieve it."
        ),
    }


# -------------------------------------------------------- transaction price

@router.get("/transaction-price", summary="Recorded transaction prices, where held")
async def transactions(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    d = market_reference.transaction_reference(c.id)
    d["city"] = {"id": c.id, "name": c.name}
    return d


# ------------------------------------------------------------ revenue layer

@router.get("/revenue-coverage", summary="Taluks, hoblis and villages actually held")
async def revenue_coverage(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    if c.id != "bengaluru":
        return {
            "city": {"id": c.id, "name": c.name},
            "available": False,
            "reason": (
                f"No revenue-sheet layer has been ingested for {c.name}. Taluk, "
                "hobli, village and survey number are unavailable there."
            ),
        }
    cov = revenue.coverage()
    cov["city"] = {"id": c.id, "name": c.name}
    cov["survey_number_caveat"] = revenue.SURVEY_CAVEAT
    return cov
