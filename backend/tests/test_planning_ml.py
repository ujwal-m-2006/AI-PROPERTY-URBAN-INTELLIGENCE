"""Planning ML — the layer ablation and ward typologies.

"Use all the datasets" is trivially satisfiable by bolting every column on and
reporting a number. What makes it a real answer is measuring each layer, which
means being willing to publish the ones that did not help.

On this data one layer makes the model measurably worse (reported flooding
distance, Bengaluru), one helps a little (road width), and Bengaluru's ward
typologies are too weakly separated to classify a ward with. All three are
negative results and all three are surfaced.
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
    p = ARTIFACTS / city / "planning_models.json"
    if not p.exists():
        pytest.skip(f"{city} planning models not trained")
    return json.loads(p.read_text(encoding="utf-8"))


def ablation(city: str) -> dict:
    r = client.get("/api/v1/planning-ml/ablation", params={"city": city})
    if r.status_code != 200:
        pytest.skip(f"{city} planning models unavailable")
    return r.json()


def typology(city: str) -> dict:
    r = client.get("/api/v1/planning-ml/typology", params={"city": city})
    if r.status_code != 200:
        pytest.skip(f"{city} planning models unavailable")
    return r.json()


# --- the ablation must be able to say "no" ------------------------------


@pytest.mark.parametrize("city", CITIES)
def test_every_step_carries_a_verdict(city: str) -> None:
    steps = ablation(city)["steps"]
    assert len(steps) >= 2
    for s in steps:
        assert s["verdict"] in ("baseline", "HELPS", "no effect", "HURTS")
        assert s["spatial_cv_r2"] is not None
        assert s["n_features"] > 0


@pytest.mark.parametrize("city", CITIES)
def test_deltas_are_consistent_with_the_scores(city: str) -> None:
    """A delta that does not match the R² it came from would be decoration."""
    steps = ablation(city)["steps"]
    for prev, cur in zip(steps, steps[1:], strict=False):
        expected = round(cur["spatial_cv_r2"] - prev["spatial_cv_r2"], 4)
        assert abs(cur["delta"] - expected) < 1e-6, (
            f"{city}: {cur['features']} delta {cur['delta']} does not match "
            f"{cur['spatial_cv_r2']} - {prev['spatial_cv_r2']}"
        )


@pytest.mark.parametrize("city", CITIES)
def test_a_verdict_matches_its_delta(city: str) -> None:
    for s in ablation(city)["steps"]:
        if s["verdict"] == "baseline":
            assert s["delta"] is None
            continue
        if s["verdict"] == "HELPS":
            assert s["delta"] > 0.005
        elif s["verdict"] == "HURTS":
            assert s["delta"] < -0.005
        else:
            assert abs(s["delta"]) <= 0.005


def test_at_least_one_layer_is_reported_as_not_helping() -> None:
    """If this ever passes trivially, the ablation has stopped being honest.

    On the current data reported-flooding distance hurts Bengaluru and taluk
    hurts Chennai. A study where every addition helps is either lucky or not
    measuring anything.
    """
    negative = 0
    for city in CITIES:
        sm = ablation(city)["summary"]
        negative += sm["hurt"] + sm["no_effect"]
    assert negative >= 1, (
        "every layer reportedly helped in both cities — verify the ablation is "
        "actually re-scoring rather than accumulating"
    )


@pytest.mark.parametrize("city", CITIES)
def test_the_best_step_is_actually_the_highest_scoring(city: str) -> None:
    d = ablation(city)
    best = max(s["spatial_cv_r2"] for s in d["steps"])
    assert d["best_r2"] == best


# --- the forbidden feature ----------------------------------------------


def test_proposed_road_width_is_excluded_by_name() -> None:
    """It encodes a planning intention, not a present condition. Feeding it to a
    price model would leak that intention into a market prediction."""
    d = ablation("bengaluru")
    excluded = d["excluded_by_name"]
    assert "width_proposed_m" in excluded
    assert "planning intention" in excluded["width_proposed_m"]

    # And it must not appear anywhere in the trained feature sets.
    blob = json.dumps(payload("bengaluru"))
    assert "width_proposed_m" in blob, "the exclusion note should be recorded"
    for step in payload("bengaluru")["ablation"]:
        assert "proposed" not in step["features"].lower()


def test_validation_is_the_same_spatial_scheme_as_the_headline_model() -> None:
    """Otherwise these R² values are not comparable with the shipped one."""
    for city in CITIES:
        v = payload(city)["validation"]
        assert "GroupKFold" in v
        assert "ward" in v or "locality" in v


# --- typologies: grouping, never ranking --------------------------------


@pytest.mark.parametrize("city", CITIES)
def test_typology_reports_its_separation_quality(city: str) -> None:
    t = typology(city)
    if not t.get("available"):
        assert t.get("reason")
        return
    assert t["silhouette"] is not None
    assert t["well_separated"] in (True, False)
    # The usability flag must follow the silhouette, not the other way round.
    assert t["usable_for_classification"] == t["well_separated"]


def test_weakly_separated_typologies_are_not_usable_for_classification() -> None:
    """Bengaluru's silhouette is ~0.27. Presenting those as ward types would
    give a planner categories the data does not support."""
    t = typology("bengaluru")
    if not t.get("available"):
        pytest.skip("bengaluru typologies unavailable")
    if t["silhouette"] < 0.35:
        assert t["usable_for_classification"] is False
        assert t["warning"]
        assert "WEAKLY SEPARATED" in t["warning"]


@pytest.mark.parametrize("city", CITIES)
def test_typologies_are_never_presented_as_a_ranking(city: str) -> None:
    t = typology(city)
    if not t.get("available"):
        pytest.skip(f"{city} typologies unavailable")
    note = t["not_a_ranking"]
    assert "not" in note.lower()
    assert "ordering" in note.lower() or "ranking" in note.lower()
    # No cluster may carry a score, rank or label implying an ordering.
    for c in t["clusters"]:
        assert set(c) <= {"typology", "wards", "examples", "profile"}


@pytest.mark.parametrize("city", CITIES)
def test_k_was_selected_not_assumed(city: str) -> None:
    t = typology(city)
    if not t.get("available"):
        pytest.skip(f"{city} typologies unavailable")
    assert "silhouette" in t["k_selection"].lower()
    assert "not assumed" in t["k_selection"].lower()


# --- the tab renders the negatives --------------------------------------


def test_frontend_tab_shows_hurt_and_weak_verdicts() -> None:
    html = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    if not html.exists():
        pytest.skip("frontend not present")
    text = html.read_text(encoding="utf-8")
    assert 'data-tab="planningml"' in text
    assert "function renderPlanningML(" in text
    # A red badge for HURTS, and the usability flag, must both be rendered.
    assert '"HURTS":"RED"' in text
    assert "usable_for_classification" in text
    assert "excluded_by_name" in text
