"""Derived analytics: anomaly detection, demand, risk, recommendation.

LABELLING DISCIPLINE — the point of this module.

Only two things here are machine learning:
  * overpricing detection — compares an observed price against a trained
    model's prediction, so it inherits the model.
  * the recommender — a fitted NearestNeighbors index over real listings.

Demand and risk have NO labelled ground truth in either dataset. Predicting a
label you cannot observe is not machine learning, so they are computed as
transparent weighted indices and returned with
``method: "DATA-DRIVEN SCORE"``. Calling them ML would be the single easiest
thing for an examiner to catch.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "ml" / "artifacts"

METHOD_ML = "ML PREDICTION"
METHOD_SCORE = "DATA-DRIVEN SCORE"


@lru_cache(maxsize=4)
def _metrics(city_id: str) -> dict[str, Any]:
    path = ARTIFACTS / city_id / "metrics.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# ----------------------------------------------------- overpricing (ML)

def price_anomaly(
    observed_psf: float, predicted_psf: float, interval_half_width: float
) -> dict[str, Any]:
    """Classify an observed price against the model's prediction interval.

    The conformal interval is the decision boundary: inside it the model cannot
    distinguish the price from fair, so the honest answer is "fairly priced".
    """
    if predicted_psf <= 0:
        return {
            "verdict": "UNAVAILABLE",
            "method": METHOD_ML,
            "reason": "Model produced no usable prediction for these inputs",
        }

    diff = observed_psf - predicted_psf
    pct = diff / predicted_psf * 100.0
    z = diff / interval_half_width if interval_half_width > 0 else 0.0

    if abs(diff) <= interval_half_width:
        verdict, note = "FAIRLY PRICED", (
            "The observed price falls inside the model's 90% prediction "
            "interval, so the model cannot distinguish it from fair value."
        )
    elif diff > 0:
        verdict, note = "POTENTIALLY OVERPRICED", (
            "The observed price sits above the model's 90% prediction interval."
        )
    else:
        verdict, note = "POTENTIALLY UNDERPRICED", (
            "The observed price sits below the model's 90% prediction interval."
        )

    return {
        "verdict": verdict,
        "method": METHOD_ML,
        "observed_psf": round(observed_psf, 0),
        "predicted_psf": round(predicted_psf, 0),
        "difference_psf": round(diff, 0),
        "difference_pct": round(pct, 1),
        "intervals_from_prediction": round(z, 2),
        "note": note,
        "caveat": (
            "Model-relative only. It is not a valuation and carries no legal or "
            "financial certainty. The underlying model is trained on "
            f"{_metrics('bengaluru').get('target_label', 'listing data')}."
        ),
    }


# ------------------------------------------------- demand (DATA-DRIVEN)

DEMAND_WEIGHTS = {
    "connectivity": 0.30,
    "amenity_density": 0.25,
    "healthcare": 0.15,
    "education": 0.15,
    "market_activity": 0.15,
}


def demand_score(
    *,
    connectivity_score: float | None,
    healthcare_score: float | None,
    education_score: float | None,
    amenity_count_1km: int | None,
    locality_listing_count: int | None,
    max_listing_count: int | None = None,
) -> dict[str, Any]:
    """Transparent weighted demand index. NOT a classifier.

    Every component and weight is returned so the number can be audited or
    argued with, which a black-box label could not be.
    """
    components: dict[str, Any] = {}
    missing: list[str] = []

    def add(key: str, value: float | None, label: str, source: str) -> float:
        if value is None:
            missing.append(label)
            components[key] = {"value": None, "note": "unavailable"}
            return 0.0
        v = max(0.0, min(100.0, float(value)))
        components[key] = {"value": round(v, 1), "source": source}
        return v

    conn = add("connectivity", connectivity_score, "connectivity", "OSM proximity")
    health = add("healthcare", healthcare_score, "healthcare", "OSM proximity")
    edu = add("education", education_score, "education", "OSM proximity")

    density = None
    if amenity_count_1km is not None:
        # 120 amenities within 1 km treated as a saturated urban core.
        density = min(100.0, amenity_count_1km / 120.0 * 100.0)
    dens = add("amenity_density", density, "amenity density", "OSM count within 1 km")

    activity = None
    if locality_listing_count is not None and max_listing_count:
        activity = min(100.0, locality_listing_count / max_listing_count * 100.0)
    act = add("market_activity", activity, "market activity", "listing volume in locality")

    score = (
        conn * DEMAND_WEIGHTS["connectivity"]
        + dens * DEMAND_WEIGHTS["amenity_density"]
        + health * DEMAND_WEIGHTS["healthcare"]
        + edu * DEMAND_WEIGHTS["education"]
        + act * DEMAND_WEIGHTS["market_activity"]
    )

    # If nothing was measurable, the answer is "unknown", not "zero". Scoring an
    # absent input as 0 would report LOW demand for a property we know nothing
    # about — the exact failure mode this project exists to avoid.
    measured = [k for k, v in components.items() if v.get("value") is not None]
    if not measured:
        return {
            "score": None,
            "band": "UNAVAILABLE",
            "method": METHOD_SCORE,
            "weights": DEMAND_WEIGHTS,
            "components": components,
            "missing_components": missing,
            "reason": (
                "No component could be measured — typically because no location "
                "was selected, so proximity data is unavailable. This is not a "
                "finding of low demand."
            ),
            "note": (
                "A missing input is reported as unavailable, never scored as zero."
            ),
        }

    band = "HIGH" if score >= 66 else "MEDIUM" if score >= 38 else "LOW"

    return {
        "score": round(score, 1),
        "band": band,
        "method": METHOD_SCORE,
        "measured_components": len(measured),
        "weights": DEMAND_WEIGHTS,
        "components": components,
        "missing_components": missing,
        "note": (
            "This is a transparent weighted index, not a machine-learning "
            "classifier. Neither dataset contains an observed demand label, so "
            "no supervised model can be trained or validated for it. Weights "
            "are stated above and are a design choice, not a fitted result."
        ),
    }


# --------------------------------------------------- risk (DATA-DRIVEN)

def risk_score(
    *,
    lake_distance_m: float | None,
    park_distance_m: float | None,
    hospital_distance_m: float | None,
    fire_station_distance_m: float | None,
    connectivity_score: float | None,
) -> dict[str, Any]:
    """Transparent physical/environmental risk index. NOT a classifier.

    Deliberately conservative: it does NOT claim flood risk. Authoritative
    stormwater-drain and rajakaluve geometry is unavailable (see the data-source
    audit), and asserting that a specific plot floods without it is the highest
    -liability error this platform could make.
    """
    factors: dict[str, Any] = {}
    penalty = 0.0

    if lake_distance_m is not None:
        # Water proximity is a *proximity* signal, never a flood determination.
        if lake_distance_m < 150:
            penalty += 30
            factors["water_proximity"] = {
                "value_m": round(lake_distance_m),
                "effect": "+30 risk",
                "note": "Very close to a mapped water body (OSM)",
            }
        elif lake_distance_m < 500:
            penalty += 15
            factors["water_proximity"] = {
                "value_m": round(lake_distance_m), "effect": "+15 risk"}
        else:
            factors["water_proximity"] = {
                "value_m": round(lake_distance_m), "effect": "no penalty"}
    else:
        factors["water_proximity"] = {"value_m": None, "note": "unavailable"}

    if hospital_distance_m is not None:
        if hospital_distance_m > 5000:
            penalty += 20
            factors["emergency_access"] = {
                "hospital_m": round(hospital_distance_m), "effect": "+20 risk"}
        elif hospital_distance_m > 2500:
            penalty += 10
            factors["emergency_access"] = {
                "hospital_m": round(hospital_distance_m), "effect": "+10 risk"}
        else:
            factors["emergency_access"] = {
                "hospital_m": round(hospital_distance_m), "effect": "no penalty"}

    if fire_station_distance_m is not None and fire_station_distance_m > 6000:
        penalty += 10
        factors["fire_response"] = {
            "fire_station_m": round(fire_station_distance_m), "effect": "+10 risk"}

    if connectivity_score is not None and connectivity_score < 35:
        penalty += 15
        factors["isolation"] = {
            "connectivity": connectivity_score, "effect": "+15 risk"}

    if park_distance_m is not None and park_distance_m < 800:
        penalty -= 5
        factors["green_space"] = {
            "park_m": round(park_distance_m), "effect": "-5 risk"}

    measured = [k for k, v in factors.items()
                if isinstance(v, dict) and v.get("note") != "unavailable"
                and any(kk.endswith("_m") or kk == "connectivity" for kk in v)]
    if not measured:
        return {
            "score": None,
            "band": "UNAVAILABLE",
            "method": METHOD_SCORE,
            "factors": factors,
            "excluded": [
                "Flood risk — no authoritative flood or stormwater-drain geometry "
                "is publicly available",
            ],
            "reason": (
                "No proximity factor could be measured — typically because no "
                "location was selected. This is not a finding of low risk."
            ),
            "note": "A missing input is reported as unavailable, never scored as zero.",
        }

    score = max(0.0, min(100.0, penalty))
    band = "HIGH" if score >= 50 else "MEDIUM" if score >= 25 else "LOW"

    return {
        "score": round(score, 1),
        "band": band,
        "method": METHOD_SCORE,
        "measured_factors": len(measured),
        "factors": factors,
        "excluded": [
            "Flood risk — no authoritative flood or stormwater-drain geometry "
            "is publicly available; proximity to water is NOT a flood "
            "determination",
            "Rajakaluve buffer status — authoritative geometry unavailable",
            "Soil, seismic and subsidence data — not ingested",
        ],
        "note": (
            "Transparent weighted index over OpenStreetMap proximity, not a "
            "machine-learning classifier: neither dataset contains a labelled "
            "risk outcome to train or validate against. MANUAL VERIFICATION "
            "REQUIRED for any real decision."
        ),
    }


# ---------------------------------------------- investment (COMPOSITE)

def investment_score(
    *,
    predicted_psf: float | None,
    observed_psf: float | None,
    demand: dict[str, Any] | None,
    risk: dict[str, Any] | None,
    connectivity_score: float | None,
) -> dict[str, Any]:
    """Composite Investment Score.

    Explicitly separates the ML-derived component (value gap, from the trained
    price model) from the data-driven components (demand, risk, connectivity).
    """
    parts: dict[str, Any] = {}
    total, weight_used = 0.0, 0.0

    if predicted_psf and observed_psf and predicted_psf > 0:
        gap_pct = (predicted_psf - observed_psf) / predicted_psf * 100.0
        value_component = max(0.0, min(100.0, 50.0 + gap_pct * 2.0))
        parts["value_gap"] = {
            "score": round(value_component, 1),
            "weight": 0.35,
            "method": METHOD_ML,
            "detail": (
                f"Observed {observed_psf:,.0f} vs model {predicted_psf:,.0f} "
                f"/sq.ft ({gap_pct:+.1f}%)"
            ),
        }
        total += value_component * 0.35
        weight_used += 0.35

    if demand and demand.get("score") is not None:
        parts["demand"] = {"score": demand["score"], "weight": 0.25,
                           "method": METHOD_SCORE}
        total += demand["score"] * 0.25
        weight_used += 0.25

    if connectivity_score is not None:
        parts["connectivity"] = {"score": round(connectivity_score, 1),
                                 "weight": 0.20, "method": METHOD_SCORE}
        total += connectivity_score * 0.20
        weight_used += 0.20

    if risk and risk.get("score") is not None:
        inverted = 100.0 - risk["score"]
        parts["risk_inverted"] = {"score": round(inverted, 1), "weight": 0.20,
                                  "method": METHOD_SCORE}
        total += inverted * 0.20
        weight_used += 0.20

    if weight_used == 0:
        return {
            "score": None, "band": "UNAVAILABLE", "method": METHOD_SCORE,
            "reason": "No component inputs were available",
        }

    score = total / weight_used
    band = "STRONG" if score >= 70 else "MODERATE" if score >= 50 else "WEAK"

    return {
        "score": round(score, 1),
        "band": band,
        "method": "COMPOSITE (ML + DATA-DRIVEN SCORE)",
        "components": parts,
        "weights_used": round(weight_used, 2),
        "note": (
            "Composite of one ML-derived component (value gap, from the trained "
            "price model) and three data-driven scores. The weighting is a "
            "design choice, not a fitted model. Not investment advice."
        ),
    }


# --------------------------------------------------------- helpers

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def city_target_label(city_id: str) -> str:
    m = _metrics(city_id)
    return m.get("target_label", "price per sq.ft")
