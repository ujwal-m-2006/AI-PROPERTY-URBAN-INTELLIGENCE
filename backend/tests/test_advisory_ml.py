"""Advisory ML — negotiation band and price drivers.

These models exist to answer the buyer/seller/investor questions a point
estimate cannot. That makes them the most quotable output in the project, and
therefore the most dangerous: a "₹4,200 – ₹7,900 negotiation band" reads as
authoritative whether or not it is calibrated.

Two measured facts make it not:
  * Bengaluru's band UNDER-covers (74% against a nominal 80%).
  * Chennai's OVER-covers at 100% on 7 spatial blocks — uninformative, not good.

So the tests below are mostly about refusal: the band must never be presented as
calibrated when it is not, and an unstable price driver must never reach a
seller as advice.
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


def _payload(city: str) -> dict:
    path = ARTIFACTS / city / "advisory_models.json"
    if not path.exists():
        pytest.skip(f"{city} advisory models not trained")
    return json.loads(path.read_text(encoding="utf-8"))


def _api(city: str) -> dict:
    r = client.get("/api/v1/advisory-ml", params={"city": city})
    if r.status_code != 200:
        pytest.skip(f"{city} advisory models not available")
    return r.json()


# --- the band must report its own calibration ---------------------------


@pytest.mark.parametrize("city", CITIES)
def test_measured_coverage_is_reported_next_to_the_nominal(city: str) -> None:
    band = _payload(city)["negotiation_band"]
    assert band["nominal_coverage"] == 0.80
    assert 0.0 < band["measured_coverage"] <= 1.0
    assert "measured_coverage" in band["conformalized"]


@pytest.mark.parametrize("city", CITIES)
def test_a_miscalibrated_band_is_never_called_usable(city: str) -> None:
    """The single most important guard in this module."""
    d = _api(city)
    health = d["band_health"]
    conf = d["negotiation_band"]["conformalized"]
    if not conf["calibrated"] or conf.get("few_blocks_warning"):
        assert health["usable_as_stated"] is False
        assert "do not quote it as an 80% band" in health["verdict"].lower()


@pytest.mark.parametrize("city", CITIES)
def test_over_and_under_coverage_are_distinguished(city: str) -> None:
    """100% coverage is not 'better'. It means the band says nothing."""
    conf = _payload(city)["negotiation_band"]["conformalized"]
    assert conf["direction"] in ("on target", "OVER-COVERS", "UNDER-COVERS")
    if conf["measured_coverage"] > 0.90:
        assert conf["direction"] == "OVER-COVERS"
        assert conf["reliable"] is False


def test_chennai_band_carries_the_few_blocks_warning() -> None:
    conf = _payload("chennai")["negotiation_band"]["conformalized"]
    assert conf["few_blocks_warning"], "7 spatial blocks but no warning"
    assert "not a guarantee" in conf["few_blocks_warning"]
    assert conf["reliable"] is False


# --- quantile mechanics -------------------------------------------------


@pytest.mark.parametrize("city", CITIES)
def test_quantile_crossing_is_measured_and_handled(city: str) -> None:
    """P10 > P90 is nonsense and can happen with independent fits."""
    x = _payload(city)["negotiation_band"]["quantile_crossing"]
    assert x["rows"] >= 0
    assert "sorted per row" in x["handling"]


@pytest.mark.parametrize("city", CITIES)
def test_pinball_loss_is_reported_per_quantile(city: str) -> None:
    losses = _payload(city)["negotiation_band"]["pinball_loss"]
    assert set(losses) == {"p10", "p50", "p90"}
    assert all(v > 0 for v in losses.values())


@pytest.mark.parametrize("city", CITIES)
def test_the_split_is_spatial_not_random(city: str) -> None:
    assert "GroupShuffleSplit" in _payload(city)["split"]


def test_exchangeability_shortfall_is_explained_not_hidden() -> None:
    """The random-split figure proves the method works and isolates the cause."""
    check = _payload("bengaluru")["negotiation_band"]["conformalized"][
        "exchangeability_check"]
    assert check["random_split_coverage"] > check["spatial_split_coverage"]
    assert "exchangeable" in check["finding"]
    assert "not a defect in" in check["finding"]


# --- unstable drivers must not become advice ----------------------------


@pytest.mark.parametrize("city", CITIES)
def test_unstable_curves_are_labelled_not_given_a_direction(city: str) -> None:
    for curve in _payload(city)["what_moves_price"]["features"]:
        if not curve["stable_across_seeds"]:
            assert curve["direction"] == "UNSTABLE"
            assert "carries no information" in curve["note"]


def test_stability_was_tested_across_folds_not_just_seeds() -> None:
    """Varying only the estimator seed would not have caught the real flip."""
    stability = _payload("bengaluru")["what_moves_price"]["stability"]
    assert len(stability["seeds_tested"]) >= 3
    assert "fold" in stability["note"]
    # The observed instability must actually be recorded.
    assert stability["unstable_features"], (
        "bath/rooms/balcony flipped direction across folds — if this list is "
        "empty the stability check has stopped working"
    )


def test_seller_advice_excludes_every_unstable_driver() -> None:
    """The whole point: noise must not reach a user as guidance."""
    d = client.get("/api/v1/advisory-ml/persona",
                   params={"role": "seller", "city": "bengaluru"}).json()
    advised = {f["feature"] for f in d["what_you_could_change"]}
    excluded = set(d["excluded_as_noise"])
    assert excluded, "no drivers excluded — the stability filter is not applied"
    assert not (advised & excluded), "an unstable driver was presented as advice"
    assert "presenting noise" in d["why_excluded"]


def test_partial_dependence_is_declared_non_causal() -> None:
    for city in CITIES:
        note = _payload(city)["what_moves_price"]["not_causal"]
        assert "not" in note.lower() and "causal" in note.lower()
        assert "never as" in note


# --- personas -----------------------------------------------------------


@pytest.mark.parametrize("role", ["buyer", "seller", "investor"])
def test_each_persona_gets_its_own_reading(role: str) -> None:
    d = client.get("/api/v1/advisory-ml/persona",
                   params={"role": role, "city": "bengaluru"}).json()
    assert d["role"] == role
    assert d["reading"]
    assert d["band_health"]["usable_as_stated"] in (True, False)


def test_buyer_is_told_what_the_model_cannot_see() -> None:
    d = client.get("/api/v1/advisory-ml/persona",
                   params={"role": "buyer", "city": "bengaluru"}).json()
    blind = " ".join(d["model_cannot_see"]).lower()
    for topic in ("floor", "condition", "legal"):
        assert topic in blind


def test_investor_is_warned_against_cross_city_comparison() -> None:
    d = client.get("/api/v1/advisory-ml/persona",
                   params={"role": "investor", "city": "bengaluru"}).json()
    assert "Do not compare bands across cities" in d["caution"]


def test_an_unknown_role_is_rejected() -> None:
    r = client.get("/api/v1/advisory-ml/persona",
                   params={"role": "landlord", "city": "bengaluru"})
    assert r.status_code == 422
