"""What-if scenarios — re-run the model with one thing changed.

"What would this be worth with an extra bedroom?" is the question every buyer
asks, and a trained model can answer a version of it: hold everything else
fixed, change one input, predict again.

WHAT THIS IS NOT
----------------
It is **not causal**. The model learned from properties as they were listed, and
three-bedroom flats differ from two-bedroom ones in a hundred ways beyond the
bedroom count — floor, age, layout, which developments they appear in. Changing
`rooms` from 2 to 3 tells you what the model predicts for a property it would
describe as a 3BHK, not what adding a room to *this* property would earn. Every
response says so, because a number that looks like a return on investment will
be read as one.

TWO GUARDS THAT MAKE IT DEFENSIBLE
----------------------------------
1. **Extrapolation.** Ask for 20,000 sq.ft in a dataset whose 99th percentile is
   4,854 and the model will still answer — confidently and without basis. Every
   scenario is checked against the training range and flagged when it leaves it.

2. **Insensitivity.** If a feature barely moves the prediction, that is worth
   saying. A near-zero delta means the model does not use that feature much
   here, which is information about the model, not about the property market.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "ml" / "artifacts"

NOT_CAUSAL = (
    "MODEL-BASED SCENARIO, NOT A CAUSAL ESTIMATE. This is what the model "
    "predicts for a property described this way — not what changing this "
    "property would earn. Homes differing in one listed attribute differ in "
    "many unlisted ones, and the model cannot separate them."
)

# Ranges the models were actually trained on, per city. A scenario outside these
# is extrapolation and is labelled as such.
TRAIN_RANGE: dict[str, dict[str, tuple[float, float]]] = {
    "bengaluru": {"sqft": (520, 4854), "rooms": (1, 6), "bath": (1, 6),
                  "balcony": (0, 3)},
    "chennai": {"sqft": (565, 2434), "rooms": (1, 4), "bath": (1, 2),
                "balcony": (0, 3)},
}

# Changing these would describe a different property, not a scenario for this one.
IMMUTABLE = {
    "city": "A property cannot move to another city.",
    "locality": (
        "Changing locality asks about a different property. Use the map to "
        "select a location in that locality instead."
    ),
}

FIELDS = ("sqft", "rooms", "bath", "balcony")


@lru_cache(maxsize=4)
def _median_price(city: str) -> float | None:
    path = ARTIFACTS / city / "total_price.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("median_price")


def _range_check(city: str, field: str, value: float) -> dict[str, Any] | None:
    lo, hi = TRAIN_RANGE.get(city, {}).get(field, (None, None))
    if lo is None or lo <= value <= hi:
        return None
    return {
        "field": field,
        "value": value,
        "trained_range": [lo, hi],
        "direction": "above" if value > hi else "below",
        "warning": (
            f"{field}={value:g} is outside the range the model was trained on "
            f"({lo:g}–{hi:g}, 1st–99th percentile). The model will still return "
            "a number; it has no basis for this one."
        ),
    }


def run(*, city: str, base: dict[str, Any], changes: dict[str, Any],
        predict) -> dict[str, Any]:
    """Predict for `base`, then for `base` with `changes` applied.

    `predict` is injected so this module stays free of model-loading concerns
    and can be tested without artefacts on disk.
    """
    rejected = {k: IMMUTABLE[k] for k in changes if k in IMMUTABLE}
    applied = {k: v for k, v in changes.items()
               if k in FIELDS and v is not None and k not in IMMUTABLE}

    if not applied:
        return {
            "available": False,
            "reason": (
                "No changeable field was supplied. Adjustable: "
                f"{', '.join(FIELDS)}."
            ),
            "rejected_changes": rejected,
            "not_causal": NOT_CAUSAL,
        }

    scenario = {**base, **applied}

    before = predict(city, base)
    after = predict(city, scenario)
    if before is None or after is None:
        return {
            "available": False,
            "reason": "The price model is unavailable for this city.",
            "not_causal": NOT_CAUSAL,
        }

    delta = after - before
    pct = (delta / before * 100) if before else 0.0

    warnings = [w for f, v in applied.items()
                if (w := _range_check(city, f, float(v))) is not None]

    # A change the model barely responds to says something about the model.
    median = _median_price(city)
    negligible = abs(pct) < 1.0

    return {
        "available": True,
        "city": city,
        "changes_applied": applied,
        "rejected_changes": rejected,
        "before": {"price_per_sqft": round(before, 1)},
        "after": {"price_per_sqft": round(after, 1)},
        "delta": {
            "price_per_sqft": round(delta, 1),
            "percent": round(pct, 2),
            "direction": "higher" if delta > 0 else "lower" if delta < 0 else "unchanged",
        },
        "extrapolation_warnings": warnings,
        "reliable": not warnings and not negligible,
        "interpretation": (
            "The model barely responds to this change — under 1%. That is a "
            "fact about how much the model uses this feature here, not evidence "
            "that the market ignores it."
            if negligible else
            f"The model predicts {abs(pct):.1f}% "
            f"{'higher' if delta > 0 else 'lower'} per sq.ft for a property "
            "described this way."
        ),
        "median_property_price": median,
        "not_causal": NOT_CAUSAL,
        "adjustable_fields": list(FIELDS),
        "immutable_fields": IMMUTABLE,
    }


def sweep(*, city: str, base: dict[str, Any], field: str,
          values: list[float], predict) -> dict[str, Any]:
    """Vary one field across several values — the shape of the response.

    More honest than a single before/after: a curve shows whether the model's
    response is smooth, flat, or steps at particular values.
    """
    if field not in FIELDS:
        return {"available": False,
                "reason": f"{field} is not adjustable. Try: {', '.join(FIELDS)}."}

    points = []
    for v in values:
        pred = predict(city, {**base, field: v})
        if pred is None:
            continue
        points.append({
            "value": v,
            "price_per_sqft": round(pred, 1),
            "extrapolated": _range_check(city, field, float(v)) is not None,
        })

    if not points:
        return {"available": False, "reason": "The price model is unavailable."}

    lo = min(p["price_per_sqft"] for p in points)
    hi = max(p["price_per_sqft"] for p in points)
    return {
        "available": True,
        "field": field,
        "points": points,
        "swing": round(hi - lo, 1),
        "swing_percent": round((hi - lo) / lo * 100, 2) if lo else 0.0,
        "extrapolated_points": sum(1 for p in points if p["extrapolated"]),
        "trained_range": TRAIN_RANGE.get(city, {}).get(field),
        "not_causal": NOT_CAUSAL,
    }
