"""Guarantees for the revenue layer, market references, and the extra models.

These three features all share one hazard: each of them *could* be made to look
more complete than it is. A nearest parcel instead of "outside coverage", a
guidance value labelled VERIFIED because it sits in the database, a classifier
that predicts one class reported by its accuracy alone. Each test below pins
the honest behaviour so it cannot quietly regress.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.facts import Status
from app.services import market_reference, revenue

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "ml" / "artifacts"

# Marathahalli — inside the revenue sheets that are actually published.
INSIDE = (77.6974, 12.9591)
# Inside GBA, outside the published sheets.
OUTSIDE = (77.6200, 13.0500)


def _needs_revenue() -> None:
    if not revenue.is_available():
        pytest.skip("revenue layer not ingested")


# --- revenue layer -------------------------------------------------------


def test_coverage_declares_itself_partial() -> None:
    _needs_revenue()
    cov = revenue.coverage()
    assert cov["available"] is True
    assert cov["partial"] is True, "partial coverage must be stated, not implied"
    assert cov["taluks"] and cov["hoblis"]
    assert cov["parcel_count"] > 100


def test_point_inside_coverage_resolves_revenue_fields() -> None:
    _needs_revenue()
    f = revenue.facts(*INSIDE)
    for key in ("district", "taluk", "hobli", "village"):
        assert f[key].status is Status.VERIFIED, f"{key} did not resolve"
        assert f[key].value


def test_survey_number_is_indicative_never_verified() -> None:
    """It comes from a digitised sheet, not a survey. It settles nothing."""
    _needs_revenue()
    f = revenue.facts(*INSIDE)
    sn = f["survey_number"]
    assert sn.status in (Status.INDICATIVE, Status.UNAVAILABLE)
    assert sn.status is not Status.VERIFIED
    if sn.status is Status.INDICATIVE:
        assert any("not a legal determination" in c for c in sn.caveats)


def test_outside_coverage_refuses_rather_than_guessing() -> None:
    """The tempting bug is to return the nearest parcel. That is a fabrication."""
    _needs_revenue()
    f = revenue.facts(*OUTSIDE)
    for key in ("taluk", "hobli", "village", "survey_number"):
        assert f[key].status is Status.UNAVAILABLE
        assert f[key].value is None
    assert "partial" in f["taluk"].reason.lower()


def test_locate_returns_nothing_far_outside_bengaluru() -> None:
    _needs_revenue()
    assert revenue.locate(80.2341, 13.0418) is None    # Chennai
    assert revenue.locate(72.8700, 19.0700) is None    # Mumbai


# --- guidance value ------------------------------------------------------


@pytest.fixture()
def temp_store(tmp_path, monkeypatch):
    """Never let a test write to the real guidance store."""
    monkeypatch.setattr(market_reference, "STORE", tmp_path / "guidance.json")
    return tmp_path / "guidance.json"


def test_unrecorded_guidance_value_explains_itself(temp_store) -> None:
    out = market_reference.guidance_lookup("bengaluru", "Nowhere Nagar")
    assert out["available"] is False
    assert out["how_to_obtain"]
    assert out["portal"]["url"].startswith("https://")
    assert "no public API" in out["reason"]


def test_recorded_guidance_value_is_manual_never_verified(temp_store) -> None:
    market_reference.record_guidance(
        city="bengaluru", locality="Test Nagar",
        value_per_sqft=5500, recorded_by="tester")

    out = market_reference.guidance_lookup("bengaluru", "Test Nagar")
    assert out["available"] is True
    assert out["method"] == market_reference.METHOD_MANUAL
    assert out["method"] != "VERIFIED"
    assert out["recorded_by"] == "tester"
    assert "not a market price" in out["caveat"]


def test_guidance_value_does_not_leak_between_cities(temp_store) -> None:
    market_reference.record_guidance(
        city="bengaluru", locality="Shared Name",
        value_per_sqft=5500, recorded_by="tester")
    assert market_reference.guidance_lookup("chennai", "Shared Name")["available"] is False


def test_recording_the_same_locality_replaces_rather_than_duplicates(temp_store) -> None:
    for value in (5000, 6000):
        market_reference.record_guidance(
            city="bengaluru", locality="Test Nagar",
            value_per_sqft=value, recorded_by="tester")
    stored = json.loads(temp_store.read_text(encoding="utf-8"))["entries"]
    assert len(stored) == 1
    assert stored[0]["value_per_sqft"] == 6000


# --- transaction price ---------------------------------------------------


def test_bengaluru_has_no_transaction_prices_and_says_why() -> None:
    """Asking prices are not transactions. Presenting them as such would be
    the most consequential misrepresentation available to this project."""
    out = market_reference.transaction_reference("bengaluru")
    assert out["available"] is False
    assert "asking" in out["reason"].lower()
    assert out["alternative"]


def test_chennai_transaction_prices_declare_their_vintage() -> None:
    out = market_reference.transaction_reference("chennai")
    if not out.get("available"):
        pytest.skip("chennai dataset unavailable")
    assert out["basis"] == "RECORDED SALE PRICES"
    assert out["localities"]
    # Historical data presented as current would mislead a buyer today.
    assert "historical" in out["caveat"].lower()
    for loc in out["localities"]:
        assert loc["recorded_sales"] > 0
        assert "-" in loc["period"]


# --- extra models --------------------------------------------------------


def _extra(city: str) -> dict | None:
    path = ARTIFACTS / city / "extra_models.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_degenerate_classifier_is_reported_as_a_failure() -> None:
    """A model that predicts one class must never be reported by accuracy alone."""
    for city in ("bengaluru", "chennai"):
        d = _extra(city)
        if d is None:
            continue
        cl = d["classification"]
        never = cl.get("classes_never_predicted") or []
        if never:
            assert cl.get("warning"), (
                f"{city}: classifier never predicts {never} but carries no warning")
            assert "DEGENERATE" in cl["warning"]
            assert "not a model" in cl["warning"] or "failure to generalise" in cl["warning"]
        else:
            assert not cl.get("warning")


def test_classification_states_its_chance_line() -> None:
    """An accuracy figure without the chance line is uninterpretable."""
    for city in ("bengaluru", "chennai"):
        d = _extra(city)
        if d is None:
            continue
        cl = d["classification"]
        assert cl.get("chance_accuracy")
        assert cl.get("macro_f1") is not None
        assert "GroupShuffleSplit" in cl.get("split", "")


def test_price_bands_are_declared_as_derived_from_the_target() -> None:
    for city in ("bengaluru", "chennai"):
        d = _extra(city)
        if d is None:
            continue
        note = d["classification"].get("label_note", "")
        assert "derived from the target" in note


def test_clustering_refuses_when_there_are_too_few_localities() -> None:
    for city in ("bengaluru", "chennai"):
        d = _extra(city)
        if d is None:
            continue
        cu = d["clustering"]
        if cu.get("available"):
            assert cu["k"] >= 2
            assert cu["silhouette"] is not None
            assert cu["localities_clustered"] >= 20
        else:
            assert cu.get("reason"), "a skipped clustering run must say why"


def test_anomaly_flags_are_not_presented_as_wrongdoing() -> None:
    for city in ("bengaluru", "chennai"):
        d = _extra(city)
        if d is None:
            continue
        an = d["anomaly"]
        assert an["flagged"] < an["total"]
        assert "not evidence" in an["caveat"].lower()
        # Contamination is an assumption, and must be labelled as one.
        assert "assumption" in an["caveat"].lower()
