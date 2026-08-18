"""Model 1 — total property price, and the direct-vs-indirect comparison.

Serves `ml/artifacts/<city>/total_price.json`.

Two results here are worth more than the headline R²: modelling price per sq.ft
and multiplying by area beats modelling total price directly in BOTH cities, and
on Chennai a Ridge and a Lasso fit — near-identical models — land 2.8 R² apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from app.core.disclaimers import PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS
from app.core.problems import DataUnavailable
from app.services import cities

router = APIRouter()

ARTIFACTS = Path(__file__).resolve().parents[4] / "ml" / "artifacts"


def _payload(city_id: str) -> dict[str, Any]:
    path = ARTIFACTS / city_id / "total_price.json"
    if not path.exists():
        raise DataUnavailable(
            f"No total-price model for {city_id}. Run "
            f"`python ml/pipelines/train_total_price.py {city_id}`.",
            city=city_id,
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("", summary="Total price: 7 algorithms, direct vs indirect")
async def total_price(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    d = _payload(c.id)
    rows = d.get("direct", [])

    # Where two similar algorithms diverge sharply, that is the interesting part.
    scored = {r["model"]: r["r2"] for r in rows}
    divergence = None
    if "ridge" in scored and "lasso" in scored:
        gap = abs(scored["lasso"] - scored["ridge"])
        if gap > 0.5:
            divergence = {
                "models": ["ridge", "lasso"],
                "r2": [scored["ridge"], scored["lasso"]],
                "gap": round(gap, 4),
                "reading": (
                    "Two linear models differing only in penalty, "
                    f"{gap:.2f} R² apart. With few spatial blocks the "
                    "unpenalised fit extrapolates badly onto held-out "
                    "localities; L1 shrinkage drops the features that cause it."
                ),
            }

    return {
        "city": {"id": c.id, "name": c.name},
        "target": d.get("target"),
        "target_label": d.get("target_label"),
        "median_price": d.get("median_price"),
        "validation": d.get("validation"),
        "leakage_guard": d.get("leakage_guard", {}),
        "algorithms": rows,
        "best_direct": d.get("best_direct"),
        "indirect": d.get("indirect"),
        "comparison": d.get("comparison", {}),
        "algorithm_divergence": divergence,
        "honest_error": (
            f"The best model is out by about "
            f"{(d.get('indirect') or {}).get('mape_pct')}% on a median property "
            f"of ₹{d.get('median_price', 0):,.0f}. That is the number to quote, "
            "not R²."
        ),
        "generated_at": d.get("generated_at"),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }
