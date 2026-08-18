"""Multi-city guarantees.

Two things these tests exist to prevent:
  1. Bengaluru regressing when Chennai was added.
  2. The two cities' data, models or prices getting mixed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import analytics, cities

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "ml" / "artifacts"


# --- registry ------------------------------------------------------------


def test_bengaluru_is_the_default_and_primary_city() -> None:
    assert cities.DEFAULT_CITY == "bengaluru"
    assert cities.get().id == "bengaluru"
    assert cities.all_cities()[0].id == "bengaluru"


def test_both_cities_registered_with_correct_ward_counts() -> None:
    assert cities.get("bengaluru").ward_count == 369
    assert cities.get("chennai").ward_count == 200


def test_unknown_city_is_rejected_not_defaulted() -> None:
    with pytest.raises(KeyError):
        cities.get("mumbai")


def test_cities_never_share_a_model_directory() -> None:
    dirs = [c.model_dir for c in cities.all_cities()]
    assert len(set(dirs)) == len(dirs)


def test_cities_never_share_a_dataset_or_amenity_file() -> None:
    datasets = [c.dataset_file for c in cities.all_cities()]
    amenities = [c.amenities_file for c in cities.all_cities()]
    wards = [c.wards_file for c in cities.all_cities()]
    assert len(set(datasets)) == len(datasets)
    assert len(set(amenities)) == len(amenities)
    assert len(set(wards)) == len(wards)


def test_city_bboxes_do_not_overlap() -> None:
    """A point must never resolve to both cities."""
    b, c = cities.get("bengaluru"), cities.get("chennai")
    assert b.bbox[2] < c.bbox[0], "Bengaluru and Chennai bounding boxes overlap"


def test_point_resolves_to_exactly_one_city() -> None:
    assert cities.city_for_point(77.5946, 12.9716).id == "bengaluru"
    assert cities.city_for_point(80.2707, 13.0827).id == "chennai"
    assert cities.city_for_point(72.87, 19.07) is None  # Mumbai


# --- separation of trained models ---------------------------------------


def _metrics(city: str) -> dict | None:
    path = ARTIFACTS / city / "metrics.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def test_models_are_trained_on_their_own_city_only() -> None:
    for city in ("bengaluru", "chennai"):
        m = _metrics(city)
        if m is None:
            pytest.skip(f"{city} not trained")
        assert m["city"] == city
        assert city in m["dataset"]["source_url"].lower() or city == "bengaluru"


def test_cities_have_different_price_targets_and_say_so() -> None:
    b, c = _metrics("bengaluru"), _metrics("chennai")
    if not b or not c:
        pytest.skip("both cities must be trained")
    # Bengaluru is asking price; Chennai is recorded sale price. Conflating
    # them would be the single most misleading thing this project could do.
    assert b["target_label"] != c["target_label"]
    assert "asking" in b["target_note"].lower()
    assert "sale" in c["target_note"].lower()


def test_low_block_count_carries_a_test_score_warning() -> None:
    """A near-perfect test R2 on few spatial blocks must be flagged."""
    for city in ("bengaluru", "chennai"):
        m = _metrics(city)
        if m is None:
            continue
        blocks = m["dataset"]["spatial_blocks"]
        if blocks < 15:
            assert m.get("test_split_warning"), (
                f"{city} has only {blocks} spatial blocks but no warning on its "
                "optimistic random-split test score"
            )


# --- method labelling ----------------------------------------------------


def test_demand_is_labelled_a_score_not_a_model() -> None:
    out = analytics.demand_score(
        connectivity_score=80, healthcare_score=60, education_score=70,
        amenity_count_1km=50, locality_listing_count=None, max_listing_count=None,
    )
    assert out["method"] == analytics.METHOD_SCORE
    assert "not a machine-learning classifier" in out["note"]
    assert out["band"] in ("LOW", "MEDIUM", "HIGH")


def test_risk_is_labelled_a_score_and_excludes_flood() -> None:
    out = analytics.risk_score(
        lake_distance_m=100, park_distance_m=500, hospital_distance_m=6000,
        fire_station_distance_m=7000, connectivity_score=20,
    )
    assert out["method"] == analytics.METHOD_SCORE
    # Never claim flood risk without authoritative geometry.
    assert any("flood" in e.lower() for e in out["excluded"])


def test_overpricing_is_labelled_ml_and_respects_the_interval() -> None:
    inside = analytics.price_anomaly(5200.0, 5000.0, 1000.0)
    above = analytics.price_anomaly(8000.0, 5000.0, 1000.0)
    below = analytics.price_anomaly(2000.0, 5000.0, 1000.0)

    assert inside["verdict"] == "FAIRLY PRICED"
    assert above["verdict"] == "POTENTIALLY OVERPRICED"
    assert below["verdict"] == "POTENTIALLY UNDERPRICED"
    assert all(r["method"] == analytics.METHOD_ML for r in (inside, above, below))
    # Wording must stay hedged.
    assert "POTENTIALLY" in above["verdict"]


def test_investment_score_separates_ml_from_score_components() -> None:
    demand = analytics.demand_score(
        connectivity_score=70, healthcare_score=70, education_score=70,
        amenity_count_1km=60, locality_listing_count=None, max_listing_count=None,
    )
    risk = analytics.risk_score(
        lake_distance_m=2000, park_distance_m=600, hospital_distance_m=1000,
        fire_station_distance_m=3000, connectivity_score=70,
    )
    out = analytics.investment_score(
        predicted_psf=6000, observed_psf=5000, demand=demand, risk=risk,
        connectivity_score=70,
    )
    assert out["components"]["value_gap"]["method"] == analytics.METHOD_ML
    assert out["components"]["demand"]["method"] == analytics.METHOD_SCORE
    assert "COMPOSITE" in out["method"]


# --- missing inputs must never be scored as zero -------------------------


def test_demand_with_no_inputs_is_unavailable_not_low() -> None:
    """A property we know nothing about must not be reported as low demand."""
    out = analytics.demand_score(
        connectivity_score=None, healthcare_score=None, education_score=None,
        amenity_count_1km=None, locality_listing_count=None, max_listing_count=None,
    )
    assert out["band"] == "UNAVAILABLE"
    assert out["score"] is None
    assert "not a finding of low demand" in out["reason"]


def test_risk_with_no_inputs_is_unavailable_not_low() -> None:
    out = analytics.risk_score(
        lake_distance_m=None, park_distance_m=None, hospital_distance_m=None,
        fire_station_distance_m=None, connectivity_score=None,
    )
    assert out["band"] == "UNAVAILABLE"
    assert out["score"] is None
    assert "not a finding of low risk" in out["reason"]


def test_buyer_verdict_capped_while_records_unverified() -> None:
    """However good the numbers look, records are never machine-verifiable."""
    from app.services import advisory

    v = advisory.buyer_verdict(
        observed_psf=3000, predicted_psf=6000, interval_half=500,
        demand={"band": "HIGH", "score": 90},
        risk={"band": "LOW", "score": 5},
        connectivity=95, records_verified=False,
    )
    assert v["verdict"] == "VERIFY BEFORE PURCHASE"
    assert v["blocking"], "the records caveat must be stated"
    assert v["cap_note"]


def test_buyer_verdict_flags_unavailable_inputs_separately() -> None:
    from app.services import advisory

    v = advisory.buyer_verdict(
        observed_psf=6500, predicted_psf=5000, interval_half=2000,
        demand={"band": "UNAVAILABLE", "score": None},
        risk={"band": "UNAVAILABLE", "score": None},
        connectivity=None, records_verified=False,
    )
    joined = " ".join(v["negatives"]).lower()
    assert "could not be assessed" in joined


def test_investor_ranking_reports_partial_coverage() -> None:
    from app.services import advisory

    out = advisory.rank_options([
        {"label": "Full", "city": "bengaluru", "predicted_psf": 6000,
         "observed_psf": 5000, "demand": {"score": 70},
         "connectivity": 80, "risk": {"score": 20}},
        {"label": "Sparse", "city": "bengaluru", "predicted_psf": 6000,
         "observed_psf": 5500},
    ])
    by_label = {o["label"]: o for o in out["ranked"]}
    assert by_label["Full"]["complete"] is True
    assert by_label["Sparse"]["complete"] is False
    assert "Sparse" in out["incomplete"]


def test_investor_warns_when_comparing_across_cities() -> None:
    from app.services import advisory

    out = advisory.rank_options([
        {"label": "A", "city": "bengaluru", "predicted_psf": 6000, "observed_psf": 5000},
        {"label": "B", "city": "chennai", "predicted_psf": 7000, "observed_psf": 6000},
    ])
    assert out["cross_city"] is True
    assert "not comparable across cities" in out["cross_city_warning"]


# --- city plumbing must actually reach the right dataset -----------------


def test_proximity_facts_uses_the_requested_city_layer() -> None:
    """A city parameter that is accepted but not passed through is the worst
    kind of bug: it returns confident results from the wrong city's data."""
    from app.services import proximity

    if not proximity.is_available("chennai"):
        pytest.skip("chennai amenity layer not ingested")

    # T Nagar, Chennai. Bengaluru's layer has nothing within 5 km of here, so a
    # non-empty result proves the Chennai layer was the one consulted.
    result = proximity.facts(13.0418, 80.2341, city_id="chennai")
    assert result["available"]
    found = sum(len(v) for v in result["found"].values())
    assert found > 0, "Chennai lookup returned nothing — city_id not passed through"


def test_proximity_does_not_leak_across_cities() -> None:
    """A Bengaluru point must find nothing in the Chennai layer, and vice versa."""
    from app.services import proximity

    if not (proximity.is_available("chennai") and proximity.is_available("bengaluru")):
        pytest.skip("both amenity layers required")

    wrong = proximity.nearby(12.9794, 77.5912, city_id="chennai")   # BLR point
    assert sum(len(v) for v in wrong.values()) == 0

    right = proximity.nearby(12.9794, 77.5912, city_id="bengaluru")
    assert sum(len(v) for v in right.values()) > 0
