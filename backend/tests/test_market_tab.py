"""Guidance value and transaction price in the Market estimate tab.

Both rows were hard-coded to render "Data unavailable" with static text,
written before `market_reference` existed. One of them was actively wrong:
Chennai's transaction row said "individual registered transactions are not
published" while the platform held locality medians from 7,109 real recorded
sales. The data was there and the UI denied it.

So these tests pin the two directions that matter — a value that exists must
surface, and a value that does not must still explain itself and offer a route
to obtain it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import market_reference

client = TestClient(app)

TESTER = "pytest_market"


@pytest.fixture(autouse=True)
def _clean_store():
    """Never leave test rows in the real guidance store."""
    yield
    data = market_reference._read()
    kept = [e for e in data["entries"] if e.get("recorded_by") != TESTER]
    if len(kept) != len(data["entries"]):
        data["entries"] = kept
        market_reference._write(data)


def estimate(city: str, locality: str | None = None) -> dict:
    body = {"city": city, "sqft": 1200, "rooms": 2, "bath": 2}
    if locality:
        body["locality"] = locality
    r = client.post("/api/v1/valuation/estimate", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# --- transaction price: held data must surface --------------------------


def test_chennai_transaction_price_is_shown_not_denied() -> None:
    """The bug: real recorded sales existed and the tab said 'not published'."""
    d = estimate("chennai", "Chrompet")
    tp = d["transaction_price"]
    assert tp["value"], "Chennai transaction price is still unavailable"
    assert tp["status"] == "INDICATIVE"
    joined = " ".join(tp["caveats"])
    assert "Chrompet" in joined
    assert "recorded sales" in joined


def test_transaction_price_uses_the_locality_when_given() -> None:
    with_loc = estimate("chennai", "Chrompet")["transaction_price"]["value"]
    without = estimate("chennai")["transaction_price"]["value"]
    assert with_loc != without, "locality was ignored — same figure either way"


def test_transaction_price_declares_its_historical_period() -> None:
    tp = estimate("chennai", "Chrompet")["transaction_price"]
    joined = " ".join(tp["caveats"])
    assert "2015" in joined
    assert "historical" in joined.lower()


def test_bengaluru_transaction_price_still_refuses_with_the_reason() -> None:
    """Asking prices are not transactions. This must not have loosened."""
    tp = estimate("bengaluru")["transaction_price"]
    assert tp["value"] is None
    assert "asking" in tp["reason"].lower()


# --- guidance value: absent must explain, present must show -------------


def test_unrecorded_guidance_value_explains_how_to_obtain_it() -> None:
    gv = estimate("bengaluru")["guidance_value"]
    assert gv["value"] is None
    reason = gv["reason"]
    assert "no public API" in reason
    assert "Record it in the Market tab" in reason


def test_recorded_guidance_value_appears_in_the_estimate() -> None:
    client.post("/api/v1/extra/guidance-value",
                json={"city": "bengaluru", "locality": "Test Layout",
                      "value_per_sqft": 4800, "recorded_by": TESTER})
    gv = estimate("bengaluru", "Test Layout")["guidance_value"]
    assert gv["value"] == 4800
    joined = " ".join(gv["caveats"])
    assert "MANUAL ENTRY" in joined
    assert TESTER in joined


def test_a_recorded_guidance_value_is_never_verified() -> None:
    """It was typed in by a person. It cannot carry the top status."""
    client.post("/api/v1/extra/guidance-value",
                json={"city": "bengaluru", "locality": "Test Layout",
                      "value_per_sqft": 4800, "recorded_by": TESTER})
    gv = estimate("bengaluru", "Test Layout")["guidance_value"]
    assert gv["status"] == "INDICATIVE"
    assert gv["status"] != "VERIFIED"
    assert gv["confidence"] <= 0.6
    assert "never" in " ".join(gv["caveats"]).lower()


def test_guidance_value_does_not_leak_between_cities() -> None:
    client.post("/api/v1/extra/guidance-value",
                json={"city": "bengaluru", "locality": "Shared Name",
                      "value_per_sqft": 4800, "recorded_by": TESTER})
    assert estimate("chennai", "Shared Name")["guidance_value"]["value"] is None


# --- the tab must render whatever the fact says -------------------------


def test_market_tab_renders_facts_rather_than_hardcoding_unavailable() -> None:
    from pathlib import Path

    html = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    if not html.exists():
        pytest.skip("frontend not present")
    text = html.read_text(encoding="utf-8")
    assert "factRow(\"Guidance value\", d.guidance_value" in text
    assert "factRow(\"Transaction price\", d.transaction_price" in text
    # The old hard-coded denial must be gone.
    assert 'Guidance value</th><td><span class="badge GREY"></span>' not in text
    # And the recording workflow must be reachable from the tab.
    assert "function recordGuidance(" in text
    assert "mLocality" in text


# --- unavailable is not one state ---------------------------------------


def _frontend() -> str:
    from pathlib import Path

    html = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    if not html.exists():
        pytest.skip("frontend not present")
    return html.read_text(encoding="utf-8")


def test_recordable_and_unpublished_render_differently() -> None:
    """A grey "Data unavailable" made a working feature look broken.

    "Nobody has recorded it yet" is an invitation; "Karnataka publishes none"
    is a finding. They must not render identically.
    """
    html = _frontend()
    assert "NOT YET RECORDED" in html
    assert "NOT PUBLISHED" in html
    assert "not a missing feature" in html
    # The flat single-state rendering must be gone.
    assert '<span class="na">Data unavailable</span>\n      <div class="why">${escapeHtml(f.reason||"")}' not in html


def test_locality_is_derived_when_the_user_types_none() -> None:
    """Both fields are keyed by locality. Without this the lookup never matches
    and the row looks broken even though the feature works."""
    html = _frontend()
    assert "function localityForLookup(" in html
    assert 'pick("village")' in html
    assert "locality:localityForLookup()" in html


def test_bengaluru_transaction_price_offers_the_only_real_route() -> None:
    """It cannot be answered in bulk — so say what *can* answer it."""
    tp = estimate("bengaluru")["transaction_price"]
    assert tp["value"] is None
    assert "Encumbrance Certificate" in tp["reason"]


def test_guidance_reason_tells_the_user_where_to_look_it_up() -> None:
    for city, portal in (("bengaluru", "Kaveri"), ("chennai", "TNREGINET")):
        gv = estimate(city)["guidance_value"]
        assert gv["value"] is None
        assert portal in gv["reason"]
        assert "Record it in the Market tab" in gv["reason"]
