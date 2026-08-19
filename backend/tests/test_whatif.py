"""What-if scenarios — the honesty guards, not the arithmetic.

A what-if endpoint is trivial to build and easy to build wrongly. Ask a model
for 20,000 sq.ft when it never saw anything above 4,854 and it answers anyway,
with the same confident tone it uses inside its range. Call the difference
between two predictions a "return on investment" and a reader will act on it.

These tests hold three lines:

1. Every response, including the failures, carries the not-causal statement.
2. Inputs outside the trained range are flagged and the scenario is marked
   unreliable — never silently answered.
3. `TRAIN_RANGE` matches the data the models were actually trained on. It is
   hardcoded, so it can drift away from the datasets without anything failing;
   the last test recomputes it from the raw data and compares.

The service takes `predict` as an argument, so most of this runs on stubs and
tests the guards rather than the model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import whatif

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[2]
BASE = {"sqft": 1200, "rooms": 2, "bath": 2, "balcony": 1}
CITIES = ("bengaluru", "chennai")


def flat(_city, _spec):
    """A model that ignores every input."""
    return 5000.0


def by_rooms(_city, spec):
    """A model that responds strongly to bedroom count."""
    return 4000.0 + 500.0 * float(spec.get("rooms") or 0)


def absent(_city, _spec):
    return None


# --- the not-causal statement ---------------------------------------------

def test_not_causal_says_what_it_is_not() -> None:
    assert "NOT A CAUSAL ESTIMATE" in whatif.NOT_CAUSAL
    # The specific misreading being guarded against.
    assert "not what changing this" in whatif.NOT_CAUSAL


@pytest.mark.parametrize("out", [
    whatif.run(city="bengaluru", base=BASE, changes={"rooms": 3}, predict=by_rooms),
    whatif.run(city="bengaluru", base=BASE, changes={}, predict=by_rooms),
    whatif.run(city="bengaluru", base=BASE, changes={"rooms": 3}, predict=absent),
])
def test_every_path_carries_the_caveat(out: dict) -> None:
    """Including the two failure paths, where it is easiest to forget."""
    assert out["not_causal"] == whatif.NOT_CAUSAL


# --- what can and cannot be changed ---------------------------------------

def test_no_change_is_refused_not_answered() -> None:
    out = whatif.run(city="bengaluru", base=BASE, changes={}, predict=by_rooms)
    assert out["available"] is False
    assert "sqft" in out["reason"]


def test_city_and_locality_cannot_be_changed() -> None:
    """Changing either asks about a different property, not a scenario."""
    out = whatif.run(city="bengaluru", base=BASE,
                     changes={"city": "chennai", "locality": "Adyar", "rooms": 3},
                     predict=by_rooms)
    assert set(out["rejected_changes"]) == {"city", "locality"}
    assert out["changes_applied"] == {"rooms": 3}


def test_unknown_field_is_ignored_not_applied() -> None:
    out = whatif.run(city="bengaluru", base=BASE,
                     changes={"floor": 12, "rooms": 3}, predict=by_rooms)
    assert "floor" not in out["changes_applied"]


def test_missing_model_reports_unavailable() -> None:
    out = whatif.run(city="bengaluru", base=BASE, changes={"rooms": 3},
                     predict=absent)
    assert out["available"] is False
    assert "unavailable" in out["reason"]


# --- guard 1: extrapolation ------------------------------------------------

def test_inside_the_trained_range_is_not_flagged() -> None:
    out = whatif.run(city="bengaluru", base=BASE, changes={"sqft": 1800},
                     predict=by_rooms)
    assert out["extrapolation_warnings"] == []


@pytest.mark.parametrize("city,value", [("bengaluru", 20000), ("chennai", 9000)])
def test_above_the_trained_range_is_flagged(city: str, value: float) -> None:
    out = whatif.run(city=city, base=BASE, changes={"sqft": value},
                     predict=by_rooms)
    assert len(out["extrapolation_warnings"]) == 1
    w = out["extrapolation_warnings"][0]
    assert w["field"] == "sqft" and w["direction"] == "above"
    assert out["reliable"] is False, "extrapolated scenarios are never reliable"


def test_the_ranges_are_city_specific() -> None:
    """Chennai's dataset tops out at 2,434 sq.ft; Bengaluru's at 4,854.

    3,000 sq.ft is ordinary in one city's data and extrapolation in the other.
    A single shared range would get one of them wrong.
    """
    blr = whatif.run(city="bengaluru", base=BASE, changes={"sqft": 3000},
                     predict=by_rooms)
    chn = whatif.run(city="chennai", base=BASE, changes={"sqft": 3000},
                     predict=by_rooms)
    assert blr["extrapolation_warnings"] == []
    assert len(chn["extrapolation_warnings"]) == 1


def test_the_warning_admits_a_number_still_comes_back() -> None:
    out = whatif.run(city="bengaluru", base=BASE, changes={"sqft": 20000},
                     predict=by_rooms)
    text = out["extrapolation_warnings"][0]["warning"]
    assert "no basis" in text
    assert out["after"]["price_per_sqft"], "the prediction is still returned"


# --- guard 2: insensitivity ------------------------------------------------

def test_a_model_that_ignores_the_change_says_so() -> None:
    out = whatif.run(city="bengaluru", base=BASE, changes={"rooms": 5},
                     predict=flat)
    assert out["delta"]["percent"] == 0.0
    assert out["delta"]["direction"] == "unchanged"
    assert out["reliable"] is False
    assert "fact about how much the model uses this feature" in out["interpretation"]


def test_a_responsive_model_reports_the_direction() -> None:
    out = whatif.run(city="bengaluru", base=BASE, changes={"rooms": 3},
                     predict=by_rooms)
    assert out["before"]["price_per_sqft"] == 5000.0
    assert out["after"]["price_per_sqft"] == 5500.0
    assert out["delta"]["direction"] == "higher"
    assert out["delta"]["percent"] == 10.0
    assert out["reliable"] is True


def test_a_drop_is_reported_as_a_drop() -> None:
    out = whatif.run(city="bengaluru", base=BASE, changes={"rooms": 1},
                     predict=by_rooms)
    assert out["delta"]["direction"] == "lower"
    assert out["delta"]["price_per_sqft"] < 0


# --- the sweep -------------------------------------------------------------

def test_sweep_refuses_a_field_it_cannot_vary() -> None:
    out = whatif.sweep(city="bengaluru", base=BASE, field="price",
                       values=[1, 2], predict=by_rooms)
    assert out["available"] is False


def test_sweep_marks_which_points_are_extrapolated() -> None:
    out = whatif.sweep(city="bengaluru", base=BASE, field="sqft",
                       values=[1000, 2000, 20000], predict=by_rooms)
    assert [p["extrapolated"] for p in out["points"]] == [False, False, True]
    assert out["extrapolated_points"] == 1


def test_sweep_reports_the_swing() -> None:
    out = whatif.sweep(city="bengaluru", base=BASE, field="rooms",
                       values=[1, 2, 3], predict=by_rooms)
    assert out["swing"] == 1000.0          # 5500 - 4500
    assert out["points"][0]["price_per_sqft"] == 4500.0


def test_sweep_shows_a_shape_a_single_comparison_hides() -> None:
    """The reason the sweep exists.

    A before/after between 400 and 1,600 sq.ft would report one number. The
    real model's response is not monotonic, so that number would be read as a
    trend that does not exist.
    """
    r = client.get("/api/v1/whatif/sweep", params={"field": "sqft",
                                                   "city": "bengaluru"})
    assert r.status_code == 200
    points = r.json()["points"]
    if len(points) < 4:
        pytest.skip("price model unavailable")
    prices = [p["price_per_sqft"] for p in points]
    rising = [b > a for a, b in zip(prices, prices[1:])]
    assert any(rising) and not all(rising), "response is not a straight line"


# --- the API ---------------------------------------------------------------

@pytest.mark.parametrize("city", CITIES)
def test_endpoint_returns_before_and_after(city: str) -> None:
    r = client.post("/api/v1/whatif", json={"city": city, "sqft": 1200,
                                            "rooms": 2, "bath": 2,
                                            "change_rooms": 3})
    assert r.status_code == 200
    d = r.json()
    if not d.get("available"):
        pytest.skip("price model unavailable")
    assert d["before"]["price_per_sqft"] > 0
    assert d["after"]["price_per_sqft"] > 0
    assert d["changes_applied"] == {"rooms": 3}
    assert whatif.NOT_CAUSAL in d["disclaimers"]


@pytest.mark.parametrize("city", CITIES)
def test_endpoint_flags_extrapolation(city: str) -> None:
    r = client.post("/api/v1/whatif", json={"city": city, "sqft": 1200,
                                            "rooms": 2, "change_sqft": 20000})
    d = r.json()
    if not d.get("available"):
        pytest.skip("price model unavailable")
    assert d["extrapolation_warnings"]
    assert d["reliable"] is False


def test_endpoint_rejects_an_unsweepable_field() -> None:
    r = client.get("/api/v1/whatif/sweep", params={"field": "price"})
    assert r.status_code == 422


def test_endpoint_rejects_an_unknown_city() -> None:
    r = client.post("/api/v1/whatif", json={"city": "mysuru", "change_rooms": 3})
    assert r.status_code in (400, 404, 422)


# --- the tab -------------------------------------------------------------

def test_frontend_tab_leads_with_the_caveat() -> None:
    """The warning must be in the markup, not only in the JSON.

    A user reads the tab, not the API response. If the not-causal line only
    exists in a field the page never renders, the guard is not doing anything.
    """
    html = ROOT / "frontend" / "index.html"
    if not html.exists():
        pytest.skip("frontend not present")
    text = html.read_text(encoding="utf-8")
    assert 'data-tab="whatif"' in text
    assert "function renderWhatIf(" in text
    assert "not a return on investment" in text
    assert "extrapolation_warnings" in text
    assert "Outside the trained range" in text


# --- the ranges are not stale ---------------------------------------------

@pytest.mark.parametrize("city", CITIES)
def test_trained_ranges_match_the_training_data(city: str) -> None:
    """`TRAIN_RANGE` is hardcoded — recompute it and check it did not drift.

    Raw datasets are not in git (212 MB), so this skips on a fresh clone. It is
    the test that matters most locally: if the guard's numbers stop describing
    the data, the guard is decoration.
    """
    pd = pytest.importorskip("pandas")
    sys.path.insert(0, str(ROOT))
    try:
        from ml.pipelines import city_config
        from ml.pipelines.harmonise import to_shared
    except ImportError:                                     # pragma: no cover
        pytest.skip("ml pipelines not importable")

    cfg = city_config.get(city)
    try:
        df, _ = cfg.clean(city_config.load_raw(cfg))
    except (FileNotFoundError, OSError):
        pytest.skip("raw dataset not present (not tracked in git)")

    shared = to_shared(df, city)
    pairs = {"sqft": "built_up_sqft", "rooms": "bedrooms", "bath": "bathrooms"}
    for field, column in pairs.items():
        col = pd.to_numeric(shared[column], errors="coerce").dropna()
        if col.empty:
            continue
        lo, hi = whatif.TRAIN_RANGE[city][field]
        p1, p99 = float(col.quantile(0.01)), float(col.quantile(0.99))
        assert abs(lo - p1) <= max(1.0, abs(p1) * 0.05), (
            f"{city}.{field} low bound {lo} but data's 1st percentile is {p1:.1f}")
        assert abs(hi - p99) <= max(1.0, abs(p99) * 0.05), (
            f"{city}.{field} high bound {hi} but data's 99th percentile is {p99:.1f}")
