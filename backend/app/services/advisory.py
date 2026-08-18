"""BUYER MODE and INVESTOR MODE (Modules 19 and 20).

Both compose services that already exist — the price model, proximity scores,
demand and risk indices — into a single verdict. Nothing new is predicted here.

Two rules the verdicts obey:

1. **A verdict is never stronger than its weakest input.** If records are
   unverified (they always are, since no government record is machine-readable),
   the buyer verdict cannot rise above "verify before purchase".

2. **The reasoning is always shown.** Every verdict returns the factors that
   produced it, positive and negative, so a user can disagree with the
   conclusion rather than simply accept it.
"""

from __future__ import annotations

from typing import Any

from app.services import analytics

# Buyer verdicts, worst to best. Ordered so a limiting factor can cap the result.
VERDICTS = [
    "HIGH RISK",
    "POTENTIALLY OVERPRICED",
    "VERIFY BEFORE PURCHASE",
    "FAIR VALUE",
    "GOOD VALUE",
]


def buyer_verdict(
    *,
    observed_psf: float | None,
    predicted_psf: float | None,
    interval_half: float | None,
    demand: dict[str, Any] | None,
    risk: dict[str, Any] | None,
    connectivity: float | None,
    records_verified: bool = False,
) -> dict[str, Any]:
    """BUYER MODE verdict with the reasoning that produced it."""
    positives: list[str] = []
    negatives: list[str] = []
    blocking: list[str] = []

    if predicted_psf is None or observed_psf is None:
        return {
            "verdict": "INSUFFICIENT DATA",
            "method": "COMPOSITE (ML + DATA-DRIVEN SCORE)",
            "positives": [], "negatives": [],
            "reason": (
                "Both an asking price and a model prediction are needed to judge "
                "value. One or both is unavailable."
            ),
        }

    gap_pct = (observed_psf - predicted_psf) / predicted_psf * 100.0
    half = interval_half or 0.0

    # Start from the price position, then let other factors move it.
    if observed_psf < predicted_psf - half:
        idx = 4                      # below the interval
        positives.append(
            f"Asking price is {abs(gap_pct):.0f}% below the model's estimate and "
            f"sits under its 90% prediction interval.")
    elif observed_psf <= predicted_psf + half:
        idx = 3                      # inside the interval
        positives.append(
            f"Asking price is within the model's 90% prediction interval "
            f"({gap_pct:+.0f}% against the estimate).")
    else:
        idx = 1                      # above the interval
        negatives.append(
            f"Asking price is {gap_pct:.0f}% above the model's estimate and "
            f"sits outside its 90% prediction interval.")

    if risk and risk.get("band") == "UNAVAILABLE":
        negatives.append(
            "Risk could not be assessed — no location selected, so no "
            "proximity data was available.")
    elif risk and risk.get("band") == "HIGH":
        idx = min(idx, 0)
        negatives.append(f"Risk index is HIGH ({risk.get('score')}/100).")
    elif risk and risk.get("band") == "LOW":
        positives.append(f"Risk index is LOW ({risk.get('score')}/100).")

    if demand and demand.get("band") == "UNAVAILABLE":
        negatives.append(
            "Demand could not be assessed — no location selected.")
    elif demand and demand.get("band") == "HIGH":
        positives.append(f"Demand index is HIGH ({demand.get('score')}/100).")
    elif demand and demand.get("band") == "LOW":
        idx = min(idx, 2)
        negatives.append(f"Demand index is LOW ({demand.get('score')}/100).")

    if connectivity is not None:
        if connectivity >= 70:
            positives.append(f"Strong public-transport access ({connectivity:.0f}/100).")
        elif connectivity < 40:
            idx = min(idx, 2)
            negatives.append(f"Weak public-transport access ({connectivity:.0f}/100).")

    # The hard cap. No government record is machine-readable, so this always
    # applies — and it is the single most important thing the buyer is told.
    if not records_verified:
        idx = min(idx, 2)
        blocking.append(
            "Khata, property tax, building approval and occupancy status could "
            "not be verified — no public API exists for any of them. These must "
            "be checked in person before any purchase decision.")

    return {
        "verdict": VERDICTS[idx],
        "method": "COMPOSITE (ML + DATA-DRIVEN SCORE)",
        "price_gap_pct": round(gap_pct, 1),
        "observed_psf": round(observed_psf),
        "predicted_psf": round(predicted_psf),
        "positives": positives,
        "negatives": negatives,
        "blocking": blocking,
        "cap_note": (
            "The verdict is capped at 'verify before purchase' while official "
            "records remain unverified, however favourable the other factors."
        ) if not records_verified else None,
        "disclaimer": (
            "Decision support only. Not a valuation, not legal advice, and not a "
            "recommendation to buy."
        ),
    }


# ----------------------------------------------------- INVESTOR MODE

INVESTOR_WEIGHTS = {
    "value_gap": 0.30,
    "demand": 0.25,
    "connectivity": 0.20,
    "risk_inverted": 0.25,
}


def rank_options(options: list[dict[str, Any]]) -> dict[str, Any]:
    """INVESTOR MODE — score and rank several locations against each other.

    Each option carries whatever the other services produced for it. Options
    missing a component are scored on what they have, and the weight actually
    used is reported so a partial comparison is not mistaken for a complete one.
    """
    scored: list[dict[str, Any]] = []

    for o in options:
        parts: dict[str, Any] = {}
        total = weight_used = 0.0

        pred, obs = o.get("predicted_psf"), o.get("observed_psf")
        if pred and obs and pred > 0:
            gap = (pred - obs) / pred * 100.0
            v = max(0.0, min(100.0, 50.0 + gap * 2.0))
            parts["value_gap"] = {"score": round(v, 1), "method": analytics.METHOD_ML,
                                  "detail": f"{gap:+.1f}% against the model estimate"}
            total += v * INVESTOR_WEIGHTS["value_gap"]
            weight_used += INVESTOR_WEIGHTS["value_gap"]

        for key, src in (("demand", "demand"), ("connectivity", "connectivity")):
            val = o.get(src)
            if isinstance(val, dict):
                val = val.get("score")
            if val is not None:
                parts[key] = {"score": round(float(val), 1),
                              "method": analytics.METHOD_SCORE}
                total += float(val) * INVESTOR_WEIGHTS[key]
                weight_used += INVESTOR_WEIGHTS[key]

        risk = o.get("risk")
        rscore = risk.get("score") if isinstance(risk, dict) else risk
        if rscore is not None:
            inv = 100.0 - float(rscore)
            parts["risk_inverted"] = {"score": round(inv, 1),
                                      "method": analytics.METHOD_SCORE}
            total += inv * INVESTOR_WEIGHTS["risk_inverted"]
            weight_used += INVESTOR_WEIGHTS["risk_inverted"]

        score = (total / weight_used) if weight_used else None
        scored.append({
            "label": o.get("label", "Option"),
            "city": o.get("city"),
            "score": round(score, 1) if score is not None else None,
            "band": (
                None if score is None else
                "STRONG" if score >= 70 else "MODERATE" if score >= 50 else "WEAK"
            ),
            "components": parts,
            "weight_coverage": round(weight_used, 2),
            "complete": abs(weight_used - 1.0) < 0.001,
            "observed_psf": o.get("observed_psf"),
            "predicted_psf": o.get("predicted_psf"),
        })

    ranked = sorted(
        scored, key=lambda s: (s["score"] is not None, s["score"] or 0), reverse=True)
    for i, s in enumerate(ranked, 1):
        s["rank"] = i

    cities = {s["city"] for s in ranked if s.get("city")}
    cross_city = len(cities) > 1

    return {
        "ranked": ranked,
        "weights": INVESTOR_WEIGHTS,
        "method": "COMPOSITE (ML + DATA-DRIVEN SCORE)",
        "cross_city": cross_city,
        "cross_city_warning": (
            "These options span more than one city. The two cities' price models "
            "are trained on DIFFERENT targets — Bengaluru on asking prices, "
            "Chennai on recorded sale prices from an older period. The value-gap "
            "component is therefore not comparable across cities, and the "
            "ranking should be read within a city, not across them."
        ) if cross_city else None,
        "incomplete": [s["label"] for s in ranked if not s["complete"]],
        "note": (
            "Weighted composite of one ML component (value gap) and three "
            "data-driven scores. The weights are a design choice, not a fitted "
            "result. Not investment advice."
        ),
    }
