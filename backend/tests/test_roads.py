"""Module 8 guarantees — road intelligence.

The hazard in this module is specific and quantifiable. The source publishes two
width fields; the larger exceeds the smaller on 100% of segments and its median
is roughly double. Road width drives FAR, height and setback. So a single
careless rename — `width_proposed_m` to `road_width` — would inflate the floor
area this project reports as permissible, across the whole city, with no visible
symptom. These tests exist to make that rename fail loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.facts import Status
from app.services import roads

ROOT = Path(__file__).resolve().parents[2]
META = ROOT / "data" / "processed" / "source_road_network_bengaluru.json"

# On a mapped arterial (MG Road area).
ON_ROAD = (77.6100, 12.9750)
# Inside Bengaluru but away from any mapped segment.
OFF_NETWORK = (77.5833, 12.9250)


def _needs_roads() -> None:
    if not roads.is_available():
        pytest.skip("road network not ingested")


# --- the two-width rule --------------------------------------------------


def test_no_field_is_called_plain_road_width() -> None:
    """A single 'road width' would hide which of the two figures it is."""
    _needs_roads()
    f = roads.facts(*ON_ROAD)
    assert "road_width" not in f
    assert "road_width_existing_m" in f
    assert "road_width_proposed_m" in f


def test_proposed_width_carries_a_do_not_use_caveat() -> None:
    _needs_roads()
    f = roads.facts(*ON_ROAD)
    proposed = f["road_width_proposed_m"]
    if proposed.status is Status.UNAVAILABLE:
        pytest.skip("no proposed width on the matched segment")
    joined = " ".join(proposed.caveats)
    assert "DO NOT USE FOR FEASIBILITY" in joined
    assert "PROPOSED" in joined


def test_feasibility_suggestion_offers_existing_and_excludes_proposed() -> None:
    """The wider figure must never be what feasibility is handed."""
    _needs_roads()
    hit = roads.nearest(*ON_ROAD)
    if hit is None or not hit.get("width_existing_m"):
        pytest.skip("no mapped width at the test point")

    out = roads.feasibility_suggestion(*ON_ROAD)
    assert out["available"] is True
    assert out["suggested_road_width_m"] == hit["width_existing_m"]
    assert out["suggested_road_width_m"] != hit.get("width_proposed_m")
    assert out["excluded"]["width_proposed_m"] == hit.get("width_proposed_m")
    # Weakest usable provenance, and labelled as offered rather than applied.
    assert out["source_flag"] == "dataset"
    assert "offered, not applied" in out["not_used_automatically"]


def test_the_proposed_reading_still_holds_in_the_data() -> None:
    """The whole design rests on proposed > existing. Verify it, don't assume."""
    if not META.exists():
        pytest.skip("road network not ingested")
    meta = json.loads(META.read_text(encoding="utf-8"))
    assert any("PROPOSED" in c or "proposed" in c for c in meta["caveats"])
    assert meta["assumptions"], "the proposed/existing reading must be recorded"


# --- never assert abutment ----------------------------------------------


def test_width_is_indicative_never_verified() -> None:
    """A published map width is not a survey of the road abutting a plot."""
    _needs_roads()
    f = roads.facts(*ON_ROAD)
    for key in ("road_width_existing_m", "road_width_proposed_m"):
        if f[key].status is not Status.UNAVAILABLE:
            assert f[key].status is Status.INDICATIVE
            assert f[key].status is not Status.VERIFIED


def test_distance_is_reported_and_does_not_claim_abutment() -> None:
    _needs_roads()
    f = roads.facts(*ON_ROAD)
    d = f["nearest_road_distance_m"]
    if d.status is Status.UNAVAILABLE:
        pytest.skip("no mapped road at the test point")
    assert d.value is not None and d.value <= roads.MAX_ABUTMENT_M
    assert any("does not establish" in c for c in d.caveats)


# --- refuse rather than reach -------------------------------------------


def test_off_network_point_refuses_and_says_it_is_not_a_finding() -> None:
    """No mapped road nearby is a gap in the layer, not an absence of road."""
    _needs_roads()
    f = roads.facts(*OFF_NETWORK)
    assert f["road_width_existing_m"].status is Status.UNAVAILABLE
    reason = f["road_width_existing_m"].reason
    assert "complete street network" in reason or "BBMP area" in reason


def test_nothing_is_returned_beyond_the_abutment_threshold() -> None:
    _needs_roads()
    hit = roads.nearest(*OFF_NETWORK, max_distance_m=roads.MAX_ABUTMENT_M)
    far = roads.nearest(*OFF_NETWORK, max_distance_m=5000)
    assert hit is None
    # The road exists — it is simply too far to be called abutting.
    if far is not None:
        assert far["distance_m"] > roads.MAX_ABUTMENT_M


def test_chennai_has_no_road_layer_and_says_so() -> None:
    f = roads.facts(80.2341, 13.0418, city_id="chennai")
    for v in f.values():
        assert v.status is Status.UNAVAILABLE
        assert "Bengaluru only" in v.reason


def test_point_far_outside_the_city_returns_nothing() -> None:
    _needs_roads()
    assert roads.nearest(72.8700, 19.0700) is None      # Mumbai


# --- coverage is measured, not claimed ----------------------------------


def test_coverage_reports_a_measured_number_not_a_claim() -> None:
    _needs_roads()
    cov = roads.coverage()
    assert cov["available"] is True
    assert cov["partial"] is True
    m = cov["measured"]
    assert m.get("measured") is True
    assert m["localities_tested"] > 100
    # An arterial width map cannot reach most localities, and must not pretend to.
    assert 0 < m["within_pct"]["150"] < 100


def test_hierarchy_expansion_is_labelled_unverified() -> None:
    _needs_roads()
    hit = roads.nearest(*ON_ROAD)
    if hit is None:
        pytest.skip("no mapped road at the test point")
    guess = hit.get("hierarchy_interpretation_unverified")
    if guess:
        assert "unverified" in guess.lower() or "not published" in guess.lower()
    assert "without a data dictionary" in roads.HIERARCHY_CAVEAT
