"""Advisory ML — the negotiation band and what moves price, per persona.

Serves `ml/artifacts/<city>/advisory_models.json`, produced by
`ml/pipelines/train_advisory_models.py`.

Every number here is returned with the honest verdict attached. Two of them are
uncomfortable and both are surfaced rather than buried:

  * The Bengaluru band **under-covers** (74.3% against a nominal 80%) because
    validation holds out whole localities, which breaks the exchangeability
    conformal prediction assumes. The same procedure reaches 80.8% under a
    random split, so the method is right and the gap is the cost of honest
    validation.
  * The Chennai band **over-covers** at 100% on 7 spatial blocks. A band that
    contains everything is uninformative, not accurate.

A caller that wants a single confident number will not find one here.
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

NOT_A_NEGOTIATING_POSITION = (
    "These are quantiles of the price the model was trained on — asking price "
    "for Bengaluru, recorded sale price for Chennai. They are not a valuation, "
    "not an offer, and not a negotiating position endorsed by anyone."
)


def _advisory(city_id: str) -> dict[str, Any]:
    path = ARTIFACTS / city_id / "advisory_models.json"
    if not path.exists():
        raise DataUnavailable(
            f"No advisory models for {city_id}. Run "
            f"`python ml/pipelines/train_advisory_models.py {city_id}`.",
            city=city_id,
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _band_health(band: dict[str, Any]) -> dict[str, Any]:
    """One place that decides whether the band may be quoted as calibrated."""
    conf = band.get("conformalized", {})
    reliable = bool(conf.get("reliable"))
    return {
        "usable_as_stated": reliable,
        "coverage_target": conf.get("target_coverage"),
        "coverage_measured": conf.get("measured_coverage"),
        "direction": conf.get("direction"),
        "verdict": (
            "Coverage is on target — the band may be quoted as an 80% band."
            if reliable else
            f"Coverage {conf.get('measured_coverage', 0):.0%} against a "
            f"{conf.get('target_coverage', 0.8):.0%} target "
            f"({conf.get('direction')}). Treat the width as INDICATIVE and do "
            "not quote it as an 80% band."
        ),
        "few_blocks_warning": conf.get("few_blocks_warning"),
    }


@router.get("", summary="Negotiation band and price drivers")
async def advisory(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    d = _advisory(c.id)
    band = d["negotiation_band"]
    return {
        "city": {"id": c.id, "name": c.name},
        "target_label": d.get("target_label"),
        "split": d.get("split"),
        "spatial_blocks": d.get("spatial_blocks"),
        "negotiation_band": band,
        "band_health": _band_health(band),
        "what_moves_price": d["what_moves_price"],
        "generated_at": d.get("generated_at"),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS,
                        NOT_A_NEGOTIATING_POSITION],
    }


@router.get("/persona", summary="The same models, framed for one party")
async def persona(
    role: str = Query("buyer", pattern="^(buyer|seller|investor)$"),
    city: str = Query("bengaluru"),
) -> dict[str, Any]:
    """Buyer, seller and investor need different readings of the same band."""
    c = cities.get(city)
    d = _advisory(c.id)
    band = d["negotiation_band"]
    health = _band_health(band)
    interp = band.get("interpretation", {})

    # Only stable curves may be presented as guidance. An unstable direction is
    # noise, and dressing it as advice is how a model misleads someone.
    curves = d["what_moves_price"]["features"]
    stable = [c_ for c_ in curves if c_.get("stable_across_seeds")]
    unstable = [c_["feature"] for c_ in curves if not c_.get("stable_across_seeds")]

    out: dict[str, Any] = {
        "city": {"id": c.id, "name": c.name},
        "role": role,
        "reading": interp.get(role),
        "band_health": health,
        "quantiles": {
            "p10": "defensible low offer",
            "p50": "realistic midpoint",
            "p90": "ambitious but evidenced ask",
        },
        "band_width_pct_of_price": band.get(
            "conformalized", {}).get("median_width_pct_of_price"),
    }

    if role == "seller":
        out["what_you_could_change"] = [
            {"feature": s["feature"], "direction": s["direction"],
             "swing": s["swing"],
             "swing_pct_of_median": s["swing_pct_of_median"]}
            for s in stable
        ]
        out["excluded_as_noise"] = unstable
        out["why_excluded"] = (
            "These features' partial-dependence direction flipped between "
            "independent spatial splits, so the model has not learned a stable "
            "relationship. Presenting them as advice would be presenting noise."
        )
        out["not_causal"] = d["what_moves_price"]["not_causal"]
    elif role == "buyer":
        out["how_to_use"] = (
            "Compare the asking price against P10 and P50. Above P90 the "
            "listing is in the top decile for its type and area — which may be "
            "justified by things the model cannot see (floor, view, condition, "
            "legal status), so it is a question to ask, not a verdict."
        )
        out["model_cannot_see"] = [
            "floor level and view", "construction quality and condition",
            "legal status, encumbrances and approvals",
            "maintenance charges", "actual carpet area",
        ]
    else:
        out["how_to_use"] = (
            "Band width is the market's disagreement about this property type "
            "in this area. Read it alongside the model's spatial-CV R², not "
            "instead of it — a narrow band from a weak model is false comfort."
        )
        out["caution"] = (
            "Do not compare bands across cities. Bengaluru's target is asking "
            "price and Chennai's is recorded sale price, over different periods."
        )

    out["disclaimers"] = [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS,
                          NOT_A_NEGOTIATING_POSITION]
    return out
