"""Tests for the price model service.

These guard the honesty properties, not the accuracy. A model that gets better
must not be allowed to get more confident than its data supports.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.facts import Status, Tier
from app.services import valuation as svc

ARTIFACTS = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
trained = pytest.mark.skipif(
    not (ARTIFACTS / "price_model.joblib").exists(),
    reason="model not trained; run ml/pipelines/train_price_model.py",
)


@pytest.fixture
def result():
    return svc.estimate(
        svc.ValuationInput(sqft=1200, rooms=2, bath=2, balcony=1, corporation="East")
    )


@trained
def test_prediction_is_estimated_never_verified(result) -> None:
    assert result["price_per_sqft"].status is Status.ESTIMATED
    assert result["price_per_sqft"].colour == "AMBER"


@trained
def test_prediction_carries_an_interval(result) -> None:
    low = result["price_range_low"].value
    high = result["price_range_high"].value
    point = result["price_per_sqft"].value
    assert low < point < high, "a point estimate must sit inside its interval"


@trained
def test_confidence_is_capped_regardless_of_model_quality(result) -> None:
    assert result["price_per_sqft"].confidence <= svc.MAX_MARKET_CONFIDENCE
    assert result["price_per_sqft"].tier is Tier.T4


@trained
def test_asking_price_bias_is_disclosed(result) -> None:
    caveats = " ".join(result["price_per_sqft"].caveats).lower()
    assert "asking" in caveats
    assert "transaction" in caveats


@trained
def test_guidance_and_transaction_price_are_unavailable(result) -> None:
    # Neither is publicly obtainable. If either ever returns a value, something
    # has started inventing government data.
    assert result["guidance_value"].status is Status.UNAVAILABLE
    assert result["transaction_price"].status is Status.UNAVAILABLE


@trained
def test_estimated_value_declares_its_assumptions(result) -> None:
    assert result["estimated_value"].assumptions
    assert result["estimated_value"].status is Status.ESTIMATED


def test_untrained_model_returns_unavailable_not_a_guess(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_bundle", lambda city="bengaluru": None)
    out = svc.estimate(svc.ValuationInput(sqft=1200, rooms=2))
    assert all(f.status is Status.UNAVAILABLE for f in out.values())
    assert all(f.value is None for f in out.values())


# --- the methodological finding, pinned -----------------------------------


@trained
def test_spatial_cv_is_reported_and_lower_than_random_cv() -> None:
    """Random k-fold must never be the headline score.

    If this fails, either the spatial split stopped being spatial or someone
    started reporting the flattering number.
    """
    metrics = json.loads((ARTIFACTS / "metrics.json").read_text(encoding="utf-8"))
    for feature_set, models in metrics["results_by_feature_set"].items():
        for name, scores in models.items():
            if name == "baseline_median":
                continue
            assert scores["spatial_cv"]["rmse_r2"] <= scores["random_cv"]["rmse_r2"], (
                f"{feature_set}/{name}: spatial CV scored above random CV, which "
                "means the grouping is no longer blocking geographic leakage"
            )


@trained
def test_locality_features_leak_more_than_they_help() -> None:
    """The project's headline finding, as an assertion."""
    metrics = json.loads((ARTIFACTS / "metrics.json").read_text(encoding="utf-8"))
    with_loc = metrics["results_by_feature_set"]["with_locality"]["hist_gradient_boosting"]
    without = metrics["results_by_feature_set"]["without_locality"]["hist_gradient_boosting"]

    assert with_loc["random_cv"]["rmse_r2"] > without["random_cv"]["rmse_r2"]
    assert with_loc["leakage_gap_r2"] > without["leakage_gap_r2"]
    # Adding locality raises the random-CV score while lowering the honest one.
    assert with_loc["spatial_cv"]["rmse_r2"] < without["spatial_cv"]["rmse_r2"]


@trained
def test_conformal_coverage_is_close_to_nominal() -> None:
    metrics = json.loads((ARTIFACTS / "metrics.json").read_text(encoding="utf-8"))
    coverage = metrics["conformal"]["empirical_coverage"]
    target = 1 - metrics["conformal"]["alpha"]
    assert abs(coverage - target) < 0.05, (
        f"conformal coverage {coverage} strayed from nominal {target}"
    )
