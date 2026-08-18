"""Module 12 — reported flooding locations.

Audit task R7 located this dataset and left it uningested with a condition:
point data with no return period, depth or drainage may support *"flooding has
been reported N metres away"*, and may never become a risk score.

That condition is the whole test file. A "flood risk: 62/100" derived from a
list of reported addresses would be a hazard model nobody built — and it is the
single most tempting thing to do with this layer, because it looks like exactly
the number the spec asks for.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.facts import Status
from app.services import flood

client = TestClient(app)

# MG Road — inside the reported set.
NEAR = (77.6100, 12.9750)
BLR_POINT = {"lat": 12.9750, "lng": 77.6100}


def _needs() -> None:
    if not flood.is_available():
        pytest.skip("flood layer not ingested")


# --- the condition R7 attached ------------------------------------------


def test_flood_is_still_excluded_from_the_risk_score() -> None:
    """The layer exists now. It must still not feed the score."""
    r = client.post("/api/v1/insights/analyze",
                    json={"city": "bengaluru", **BLR_POINT, "sqft": 1200,
                          "rooms": 2, "bath": 2, "asking_price_per_sqft": 6500})
    risk = r.json()["risk"]
    excluded = " ".join(str(e) for e in risk.get("excluded", []))
    assert "flood" in excluded.lower(), (
        "flood has been folded into the environmental risk score — the source "
        "has no return period, depth or drainage data and cannot support it"
    )


def test_the_endpoint_says_it_is_not_a_score() -> None:
    _needs()
    d = client.get("/api/v1/flood", params={**BLR_POINT, "city": "bengaluru"}).json()
    assert d["is_a_risk_score"] is False
    assert "cannot support a risk percentage" in d["why_not_a_score"]
    assert "never folded into it" in d["excluded_from_risk_score"]


def test_no_response_field_is_named_like_a_score() -> None:
    """A key called `flood_risk_score` is all it would take for a reader to
    treat proximity as a hazard rating. The three keys that mention "score" are
    explicit denials, and only those are allowed."""
    _needs()
    d = client.get("/api/v1/flood", params={**BLR_POINT, "city": "bengaluru"}).json()
    DENIALS = {"is_a_risk_score", "why_not_a_score", "excluded_from_risk_score"}
    scoreish = {k for k in d if "score" in k.lower()} - DENIALS
    assert not scoreish, f"{sorted(scoreish)} read as a risk score"
    assert "risk_score" not in d
    assert "flood_risk" not in d
    # Distances and counts are fine; a bare 0-100 rating is not.
    assert set(d) & {"nearest_m", "count_within_radius"}


# --- the asymmetry ------------------------------------------------------


def test_absence_is_never_reported_as_safety() -> None:
    """No nearby point is not evidence of no flooding, and must say so."""
    _needs()
    # Far corner of the bbox with no reported points.
    d = client.get("/api/v1/flood",
                   params={"lat": 13.30, "lng": 77.30, "city": "bengaluru"}).json()
    assert d["nearest_m"] is None
    assert "NOT evidence" in d["absence_note"]


def test_the_fact_for_an_empty_area_carries_the_absence_note() -> None:
    _needs()
    f = flood.facts(77.30, 13.30)
    nearest = f["nearest_reported_flooding_m"]
    assert nearest.status is Status.UNAVAILABLE
    assert "NOT evidence" in nearest.reason


# --- normal operation ---------------------------------------------------


def test_reported_locations_are_found_and_ordered() -> None:
    _needs()
    hits = flood.nearby(*NEAR)
    assert hits, "no reported flooding near MG Road"
    distances = [h["distance_m"] for h in hits]
    assert distances == sorted(distances), "results are not nearest-first"
    assert all(h["kind"] for h in hits)


def test_facts_are_indicative_never_verified() -> None:
    _needs()
    f = flood.facts(*NEAR)
    for key in ("nearest_reported_flooding_m", "reported_flooding_within_2km"):
        fact = f[key]
        if fact.status is not Status.UNAVAILABLE:
            assert fact.status is Status.INDICATIVE
            assert fact.status is not Status.VERIFIED
            assert any("not a flood risk score" in c.lower() for c in fact.caveats)


def test_three_source_layers_are_kept_distinguishable() -> None:
    """Merging them into one 'flood' blob loses what each actually says."""
    _needs()
    kinds = flood.coverage()["kinds"]
    assert len(kinds) >= 2, f"layers were merged: {kinds}"
    assert sum(kinds.values()) == flood.coverage()["points"]


def test_chennai_has_no_flood_layer_and_says_so() -> None:
    d = client.get("/api/v1/flood",
                   params={"lat": 13.0418, "lng": 80.2341, "city": "chennai"}).json()
    assert d["available"] is False
    assert "Bengaluru only" in d["reason"]
    assert "not a finding" in d["not_a_finding"].lower()


def test_coverage_declares_the_layer_is_not_a_hazard_model() -> None:
    _needs()
    cov = flood.coverage()
    assert cov["is_a_risk_score"] is False
    joined = " ".join(cov["caveats"])
    assert "not a hazard model" in joined.lower()
    assert "POINT DATA" in joined
