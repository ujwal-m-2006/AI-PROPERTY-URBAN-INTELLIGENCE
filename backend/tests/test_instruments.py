"""Phase 0.5 findings — the governing instruments.

The research pass closed audit tasks R2, R3 and R4: the documents that govern
development control here are now identified and linked. The hazard that creates
is subtle and worth stating plainly.

Naming a source makes an answer *look* authoritative. A response that cites
"UDD 235 MNJ 2025, notified 05.01.2026" reads as though someone has read it. Nobody
has: the clauses are not transcribed. So the invariant these tests protect is
that citing an instrument must never cause a value to be published.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import instruments

client = TestClient(app)

PLOT = {"plot_area_sqm": 929, "road_width_m": 12.2, "land_use": "residential"}


def _evaluate() -> dict:
    r = client.post("/api/v1/feasibility/evaluate", json=PLOT)
    assert r.status_code == 200
    return r.json()


# --- the invariant -------------------------------------------------------


def test_citing_an_instrument_does_not_publish_a_far() -> None:
    """The whole point. Sources named, values still withheld."""
    d = _evaluate()
    gi = d["ruleset"]["governing_instruments"]

    assert gi["zoning_amendment"]["reference"] == "UDD 235 MNJ 2025"
    assert gi["corporation_byelaws"]["instrument_count"] == 5

    far = d["data"]["far"]
    assert far["status"] == "UNAVAILABLE"
    assert far["value"] is None


def test_every_located_instrument_declares_it_is_not_transcribed() -> None:
    gi = instruments.governing_instruments()
    assert gi["transcription_status"] == "NOT TRANSCRIBED"
    for key in ("zoning_amendment", "corporation_byelaws"):
        assert gi[key]["status"] == "LOCATED — NOT TRANSCRIBED"
    assert "guess wearing a citation" in gi["why_values_are_still_unavailable"]


def test_far_reason_names_the_instrument_and_still_refuses() -> None:
    d = _evaluate()
    reason = d["data"]["far"]["reason"]
    assert "UDD 235 MNJ 2025" in reason
    assert "not been transcribed" in reason
    # It must not read as though the document had been applied.
    assert "guess" in reason


def test_blocking_unknowns_still_lists_the_far_clause() -> None:
    d = _evaluate()
    joined = " ".join(d["blocking_unknowns"]).lower()
    assert "far" in joined


# --- what R3 and R4 actually established --------------------------------


def test_byelaws_are_recorded_as_per_corporation() -> None:
    """R3's finding changed a design: five instruments, not one."""
    b = instruments.CORPORATION_BYELAWS
    assert b["per_corporation"] is True
    assert len(b["corporations"]) == 5
    assert b["effective_from"] == "2026-05-14"
    assert "which corporation" in instruments.CORPORATION_NOTE


def test_a_corporation_selects_its_own_byelaws() -> None:
    gi = instruments.governing_instruments(corporation="East")
    assert "East" in gi["applicable_byelaws"]
    assert "2026" in gi["applicable_byelaws"]


def test_rmp2031_is_recorded_as_not_operative_with_the_reason() -> None:
    """R4. The withdrawn plan is named so it cannot quietly creep back in."""
    w = instruments.WITHDRAWN_PLAN
    assert "NOT NOTIFIED" in w["status"]
    assert "withdrawn" in w["why_not_used"].lower()
    assert instruments.OPERATIVE_PLAN.startswith("Revised Master Plan 2015")


def test_instruments_carry_provenance_not_just_titles() -> None:
    for doc in (instruments.ZONING_AMENDMENT, instruments.CORPORATION_BYELAWS):
        assert doc["source_url"].startswith("https://")
        assert doc["tier"] == "T2"        # republished, not fetched from gazette
        assert doc["licence"]
        assert "closed 2026-08-12" in doc["audit_task"]
