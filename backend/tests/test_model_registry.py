"""The trained-model registry.

Its whole value is that the verdicts can be negative. A registry that showed
every model as working would be worse than none — it would launder four known
failures into apparent successes.

Two of those failures were found *by building this*: Bengaluru's future-price
run was being reported as "not trained" when it had in fact run and refused, and
Chennai's forecast was labelled WORKS while losing to a naive baseline. Both are
pinned below.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import model_registry

client = TestClient(app)

CITIES = ("bengaluru", "chennai")
VERDICTS = {model_registry.WORKS, model_registry.LIMITED,
            model_registry.NOT_USABLE, model_registry.ABSENT}


def reg(city: str) -> dict:
    r = client.get("/api/v1/ml/registry", params={"city": city})
    assert r.status_code == 200, r.text
    return r.json()


def _find(city: str, name: str) -> dict:
    entry = next((m for m in reg(city)["models"] if m["name"] == name), None)
    if entry is None:
        pytest.skip(f"{city} has no '{name}' entry")
    return entry


# --- anchored to disk, not to intent ------------------------------------


@pytest.mark.parametrize("city", CITIES)
def test_every_entry_is_anchored_to_a_real_artefact(city: str) -> None:
    for m in reg(city)["models"]:
        if m["trained"]:
            assert m["artefact"], f"{m['name']} claims trained with no artefact"
            assert m["artefact"]["file"]
            assert m["artefact"]["trained_at"]


@pytest.mark.parametrize("city", CITIES)
def test_verdicts_come_from_the_fixed_vocabulary(city: str) -> None:
    for m in reg(city)["models"]:
        assert m["verdict"] in VERDICTS


@pytest.mark.parametrize("city", CITIES)
def test_the_registry_is_not_all_green(city: str) -> None:
    """If this ever passes trivially, the honesty guards have been removed."""
    verdicts = reg(city)["verdicts"]
    assert verdicts.get(model_registry.NOT_USABLE, 0) >= 1, (
        "no model is reported as unusable — but a degenerate classifier, an "
        "uncalibrated band and a refused forecast are all known to exist"
    )


@pytest.mark.parametrize("city", CITIES)
def test_both_cities_have_several_families(city: str) -> None:
    d = reg(city)
    assert len(d["families"]) >= 4
    assert d["trained_count"] >= 5


# --- the two bugs this file was written after ---------------------------


def test_a_refused_forecast_is_not_reported_as_untrained() -> None:
    """Bengaluru's pipeline ran, inspected the data, and declined. That is a
    decision, not a gap, and the registry must not flatten the two."""
    fp = _find("bengaluru", "Future price")
    assert fp["verdict"] == model_registry.NOT_USABLE
    assert fp["verdict"] != model_registry.ABSENT
    assert fp["trained"] is True
    assert "REFUSED" in fp["headline"]
    assert "possession" in fp["headline"].lower()


def test_a_forecast_that_loses_to_the_baseline_is_not_called_working() -> None:
    """Chennai's CAGR looks plausible and does not beat carrying the last
    value forward. Plausibility is not predictive value."""
    fp = _find("chennai", "Future price")
    beats = fp["metrics"].get("beats_naive_baseline")
    if beats is False:
        assert fp["verdict"] == model_registry.NOT_USABLE
        assert "DOES NOT BEAT" in fp["headline"]
    elif beats is True:
        assert fp["verdict"] == model_registry.WORKS


# --- known-bad models must stay known-bad -------------------------------


def test_chennai_classifier_is_flagged_unusable() -> None:
    entry = _find("chennai", "Price-band classifier")
    assert entry["verdict"] == model_registry.NOT_USABLE
    assert "DEGENERATE" in entry["headline"]


def test_bengaluru_classifier_reports_its_chance_line() -> None:
    entry = _find("bengaluru", "Price-band classifier")
    assert entry["metrics"]["chance_accuracy"]
    assert entry["metrics"]["accuracy"] > entry["metrics"]["chance_accuracy"]


@pytest.mark.parametrize("city", CITIES)
def test_negotiation_band_verdict_matches_its_coverage(city: str) -> None:
    entry = _find(city, "Negotiation band (P10/P50/P90)")
    measured = entry["metrics"]["measured_coverage"]
    target = entry["metrics"]["target_coverage"]
    if abs(measured - target) > 0.05:
        assert entry["verdict"] == model_registry.NOT_USABLE, (
            f"coverage {measured} vs target {target} but verdict "
            f"{entry['verdict']}"
        )


@pytest.mark.parametrize("city", CITIES)
def test_shipped_price_model_reports_both_cv_schemes(city: str) -> None:
    entry = _find(city, "Price model (shipped)")
    m = entry["metrics"]
    assert m["spatial_cv_r2"] is not None
    assert m["random_cv_r2"] is not None
    assert m["random_cv_r2"] >= m["spatial_cv_r2"], (
        "random CV should not score below spatial CV — if it does, the "
        "leakage story has changed and needs re-examining"
    )
    assert "spatial" in entry["headline"].lower()


def test_quantile_band_model_is_persisted_not_just_measured() -> None:
    """Without the saved estimators the band can only be an aggregate stat."""
    entry = _find("bengaluru", "Negotiation band (P10/P50/P90)")
    assert entry["trained"] is True
    assert entry["artefact"]["file"].endswith("quantile_band.joblib")
    assert entry["artefact"]["size_kb"] > 0


# --- the tab renders it -------------------------------------------------


def test_frontend_has_a_registry_tab() -> None:
    from pathlib import Path

    html = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    if not html.exists():
        pytest.skip("frontend not present")
    text = html.read_text(encoding="utf-8")
    assert 'data-tab="registry"' in text
    assert "function renderRegistry(" in text
    # Negative verdicts must be styled distinctly, not blended in.
    assert "TRAINED BUT NOT USABLE" in text
    assert "why_negatives_are_shown" in text
