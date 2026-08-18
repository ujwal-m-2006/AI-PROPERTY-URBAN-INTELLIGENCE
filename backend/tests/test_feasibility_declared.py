"""Feasibility: computing from declared figures, without inventing statutory ones.

All eight regulatory outputs were UNAVAILABLE because FAR blocks the chain. The
statutory FAR cannot be established here — the governing notification (UDD 235
MNJ 2025) is a 7-page scan with no text layer and no OCR engine is installed.

Two fixes were available and only one is legitimate:

  * Predict FAR from historical data. **Refused.** FAR is a statutory limit, not
    an empirical quantity; no historical FAR dataset exists; and a guessed figure
    decides how much somebody may legally build.
  * Accept a declared FAR with a source flag and compute downstream, bounding
    confidence by that flag. This is the audit's own settled pattern for road
    width, applied to the regulatory parameters.

These tests pin the second and guard against the first.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PLOT = {"plot_area_sqm": 929, "road_width_m": 12.2, "land_use": "residential"}
DECLARED = {
    **PLOT,
    "road_width_source": "official_document",
    "far": 1.75, "far_source": "official_document",
    "max_height_m": 15, "max_height_source": "official_document",
    "ground_coverage_pct": 50,
    "setback_front_m": 3, "setback_rear_m": 2, "setback_side_m": 1.5,
    "avg_unit_size_sqm": 95, "parking_per_unit": 1.5,
}

REGULATORY = ("far", "max_height", "max_built_up", "potential_floors",
              "setbacks", "ground_coverage", "parking_spaces", "potential_units")


def evaluate(body: dict) -> dict:
    r = client.post("/api/v1/feasibility/evaluate", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# --- declaring nothing must still refuse --------------------------------


def test_nothing_declared_still_refuses_the_far_chain() -> None:
    """The platform must not acquire a statutory FAR by this change.

    Setbacks and some height caps DO now fire without a declaration — they were
    read from the notification pages and carry clause citations. Everything
    downstream of FAR still refuses, which is the property that matters.
    """
    d = evaluate(PLOT)
    for key in ("far", "max_built_up", "potential_units", "parking_spaces"):
        assert d["data"][key]["value"] is None, f"{key} appeared from nowhere"
        assert d["data"][key]["reason"]
    assert d["computed_from_declared"] is False


def test_statutory_setbacks_fire_without_any_declaration() -> None:
    """Table 8 is encoded from the notification, so this needs no user input."""
    sb = evaluate(PLOT)["data"]["setbacks"]
    assert sb["value"] is not None
    joined = " ".join(sb.get("assumptions", []))
    assert "UDD 235 MNJ 2025" in joined


def test_the_refusal_names_the_way_forward() -> None:
    reason = evaluate(PLOT)["data"]["far"]["reason"]
    assert "UDD 235 MNJ 2025" in reason
    assert "far_source" in reason or "supply it" in reason.lower()


# --- declaring the figures makes every output compute -------------------


def test_all_eight_outputs_compute_when_declared() -> None:
    d = evaluate(DECLARED)
    for key in REGULATORY:
        assert d["data"][key]["value"] is not None, f"{key} still unavailable"


def test_the_arithmetic_is_correct() -> None:
    d = evaluate(DECLARED)["data"]
    assert d["max_built_up"]["value"] == pytest.approx(929 * 1.75, rel=1e-6)
    assert d["ground_coverage"]["value"]["footprint_sqm"] == pytest.approx(
        929 * 0.5, rel=1e-6)
    assert d["potential_units"]["value"] == int((929 * 1.75) // 95)
    assert d["parking_spaces"]["value"] >= d["potential_units"]["value"]


# --- and none of it may look statutory ----------------------------------


def test_declared_values_are_never_verified() -> None:
    d = evaluate(DECLARED)["data"]
    for key in ("far", "max_height"):
        assert d[key]["status"] != "VERIFIED"
        assert d[key]["confidence"] <= 0.70
        joined = " ".join(d[key]["caveats"])
        assert "DECLARED BY YOU" in joined


def test_the_response_says_the_outputs_rest_on_declared_figures() -> None:
    d = evaluate(DECLARED)
    assert d["computed_from_declared"] is True
    assert d["user_declared"]
    assert any("FAR is user-declared" in n for n in d["user_declared"])


def test_confidence_decays_down_the_derivation_chain() -> None:
    """A derived value must never be more confident than its weakest input."""
    d = evaluate(DECLARED)["data"]
    assert d["max_built_up"]["confidence"] < d["far"]["confidence"]
    assert d["potential_units"]["confidence"] <= d["max_built_up"]["confidence"]
    assert d["parking_spaces"]["confidence"] <= d["potential_units"]["confidence"]


def test_a_weaker_source_flag_produces_a_weaker_answer() -> None:
    """Otherwise the flag is decoration."""
    strong = evaluate({**DECLARED, "far_source": "official_document"})["data"]
    weak = evaluate({**DECLARED, "far_source": "estimated"})["data"]
    assert weak["far"]["confidence"] < strong["far"]["confidence"]
    assert weak["max_built_up"]["confidence"] < strong["max_built_up"]["confidence"]


def test_partial_declaration_leaves_dependents_unavailable() -> None:
    """FAR without a unit size cannot yield a unit count."""
    d = evaluate({**PLOT, "far": 1.75, "far_source": "estimated"})["data"]
    assert d["max_built_up"]["value"] is not None
    assert d["potential_units"]["value"] is None
    assert "avg_unit_size_sqm" in d["potential_units"]["reason"]
    assert d["parking_spaces"]["value"] is None


# --- the UI must not present computed figures as statutory --------------


def test_frontend_warns_when_outputs_rest_on_declared_figures() -> None:
    from pathlib import Path

    html = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    if not html.exists():
        pytest.skip("frontend not present")
    text = html.read_text(encoding="utf-8")
    assert "computed_from_declared" in text
    assert "not the statutory limits" in text
    assert "does not know your FAR" in text
    # A blank input must send null, never 0 — 0 would be a claim.
    assert 'if (!el || el.value === "") return null;' in text
