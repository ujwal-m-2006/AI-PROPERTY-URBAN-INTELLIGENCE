"""Model 1 — total property price.

The project predicted price PER SQ.FT and never modelled what a buyer actually
asks: what does this cost. Adding it raised a question worth answering — model
total price directly, or model price per sq.ft and multiply by area?

Indirect wins in both cities, which retroactively justifies the target the
project already used. But the reason these tests exist is the leakage: with
price_per_sqft = price / area, handing that column to a model predicting price
gives it the answer divided by a column it already has. The result would be a
spectacular R² and a worthless model — the failure that looks best in a report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ARTIFACTS = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
CITIES = ("bengaluru", "chennai")


def payload(city: str) -> dict:
    p = ARTIFACTS / city / "total_price.json"
    if not p.exists():
        pytest.skip(f"{city} total-price model not trained")
    return json.loads(p.read_text(encoding="utf-8"))


def api(city: str) -> dict:
    r = client.get("/api/v1/total-price", params={"city": city})
    if r.status_code != 200:
        pytest.skip(f"{city} total price unavailable")
    return r.json()


# --- the leakage that would invalidate everything -----------------------


@pytest.mark.parametrize("city", CITIES)
def test_price_per_sqft_is_forbidden_as_a_feature(city: str) -> None:
    guard = payload(city)["leakage_guard"]
    assert "price_per_sqft" in guard["forbidden_columns"]
    assert "price / area" in guard["note"]


def test_the_guard_actually_raises() -> None:
    """A warning would let a leaked run finish and report its number."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
    from pipelines.train_total_price import assert_no_leakage

    assert_no_leakage(["sqft", "rooms"], "price_inr")          # clean
    with pytest.raises(AssertionError, match="TARGET LEAKAGE"):
        assert_no_leakage(["sqft", "price_per_sqft"], "price_inr")
    with pytest.raises(AssertionError):
        assert_no_leakage(["sqft", "price_inr"], "price_inr")


@pytest.mark.parametrize("city", CITIES)
def test_no_model_scores_implausibly_well(city: str) -> None:
    """An R² above ~0.97 on held-out localities would mean a leak, not skill."""
    for row in payload(city)["direct"]:
        assert row["r2"] < 0.97, (
            f"{city}/{row['model']} scored {row['r2']} — check for leakage "
            "before believing it"
        )


# --- the comparison -----------------------------------------------------


@pytest.mark.parametrize("city", CITIES)
def test_seven_algorithms_plus_a_baseline(city: str) -> None:
    rows = payload(city)["direct"]
    names = {r["model"] for r in rows}
    assert "baseline_median" in names
    for expected in ("linear_regression", "ridge", "lasso", "decision_tree",
                     "random_forest", "extra_trees", "gradient_boosting"):
        assert expected in names, f"{expected} missing from the comparison"


@pytest.mark.parametrize("city", CITIES)
def test_every_algorithm_beats_or_matches_the_baseline_check(city: str) -> None:
    """Not an assertion that all do — a check that the baseline is reported so
    a reader can see which ones fail to clear it."""
    rows = {r["model"]: r["r2"] for r in payload(city)["direct"]}
    assert "baseline_median" in rows
    best = max(v for k, v in rows.items() if k != "baseline_median")
    assert best > rows["baseline_median"]


@pytest.mark.parametrize("city", CITIES)
def test_indirect_and_direct_are_both_reported(city: str) -> None:
    d = payload(city)
    assert d["best_direct"]["r2"] is not None
    assert d["indirect"]["r2"] is not None
    assert d["comparison"]["winner"] in ("direct", "indirect")


@pytest.mark.parametrize("city", CITIES)
def test_the_winner_matches_the_scores(city: str) -> None:
    d = payload(city)
    direct, indirect = d["best_direct"]["r2"], d["indirect"]["r2"]
    expected = "direct" if direct >= indirect else "indirect"
    assert d["comparison"]["winner"] == expected


def test_indirect_wins_in_both_cities() -> None:
    """The finding, and it justifies the project's existing price/sq.ft target.
    If this ever flips, the README claim needs rewriting."""
    for city in CITIES:
        assert payload(city)["comparison"]["winner"] == "indirect"


# --- honest reporting ----------------------------------------------------


@pytest.mark.parametrize("city", CITIES)
def test_error_is_quoted_in_rupees_not_only_r2(city: str) -> None:
    """R² on prices spanning two orders of magnitude flatters. MAE and MAPE
    are what a buyer would feel."""
    d = api(city)
    assert "%" in d["honest_error"]
    assert "₹" in d["honest_error"]
    for row in payload(city)["direct"]:
        assert row["mae"] > 0
        assert row["mape_pct"] > 0


@pytest.mark.parametrize("city", CITIES)
def test_validation_is_spatial(city: str) -> None:
    v = payload(city)["validation"]
    assert "GroupKFold" in v
    assert "ward" in v or "locality" in v


def test_chennai_ridge_lasso_divergence_is_surfaced() -> None:
    """Two linear models 2.8 R² apart is the most instructive row in the table,
    and it would be invisible if only the best model were reported."""
    d = api("chennai")
    div = d["algorithm_divergence"]
    if div is None:
        pytest.skip("ridge/lasso no longer diverge")
    assert set(div["models"]) == {"ridge", "lasso"}
    assert div["gap"] > 0.5
    assert "extrapolat" in div["reading"]
