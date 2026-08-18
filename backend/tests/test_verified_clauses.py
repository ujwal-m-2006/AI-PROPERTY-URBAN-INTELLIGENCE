"""Clauses read from the notification pages — the first statutory rules to fire.

The Zonal Regulations to RMP-2015 (UDD 235 MNJ 2025, 05.01.2026) is a 7-page
scan with no text layer. It was OCR'd, and then each clause encoded below was
read directly off the rendered page image and cross-checked against the OCR.

That second step is not ceremony. On these same pages the OCR rendered "12.0m"
as "12.Om" and "1000" as "1oo0". A digit taken from OCR could have been wrong in
a way that looked entirely plausible — and these numbers decide how close to a
boundary somebody may build.

FAR is deliberately absent. The notification amends setbacks, height, ramps and
dwelling units, and its height cap applies "irrespective of the FAR permissible".
FAR lives in Table 10 of the base RMP-2015 regulations, a document not read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

RULES = (Path(__file__).resolve().parents[1] / "rules" / "rmp2015" / "zoning.yaml")


def ruleset() -> dict:
    return yaml.safe_load(RULES.read_text(encoding="utf-8"))["ruleset"]


def evaluate(**body) -> dict:
    body.setdefault("land_use", "residential")
    r = client.post("/api/v1/feasibility/evaluate", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# --- a rule may only fire with a citation -------------------------------


def test_every_verified_rule_cites_its_clause_and_page() -> None:
    """The loader's own contract. A VERIFIED rule without a clause reference is
    exactly the 'guess wearing a citation' this project exists to avoid."""
    for rule in ruleset()["rules"]:
        if rule.get("status") != "VERIFIED":
            continue
        assert rule.get("clause"), f"{rule['id']} is VERIFIED with no clause"
        assert "UDD 235 MNJ 2025" in rule["clause"]
        assert rule.get("source_page"), f"{rule['id']} cites no page"


def test_far_is_still_not_encoded() -> None:
    """The notification does not contain the FAR table, and inventing one would
    be the most consequential fabrication available here."""
    far = next(r for r in ruleset()["rules"]
               if r["id"] == "far-by-road-width-residential")
    assert far["status"] == "UNVERIFIED"
    assert far.get("clause") is None
    assert "Table 10" in far["note"]


def test_the_engine_still_refuses_far_without_a_declaration() -> None:
    d = evaluate(plot_area_sqm=929, road_width_m=12.2)
    assert d["far"]["value"] is None


# --- Table 8, band by band ----------------------------------------------


@pytest.mark.parametrize(
    "plot_area,front,rear,side",
    [
        (50.0, 0.75, None, 0.60),     # band 1: up to 60
        (120.0, 0.90, 0.70, 0.70),    # band 2: above 60 up to 150
        (200.0, 1.00, 0.80, 0.80),    # band 3: above 150 up to 250
    ],
)
def test_table_8_metre_bands(plot_area, front, rear, side) -> None:
    sb = evaluate(plot_area_sqm=plot_area, road_width_m=12.0)["setbacks"]
    assert sb["value"]["front_m"] == front
    assert sb["value"]["rear_m"] == rear
    assert sb["value"]["side_m"] == side
    # COMPUTED, not VERIFIED: the clause is certain, but that this band applies
    # is only as certain as the plot area it was selected by.
    assert sb["status"] == "COMPUTED"


def test_percentage_band_is_not_resolved_without_plot_dimensions() -> None:
    """Band 4 is percentages of site depth and width. The engine holds neither,
    so it reports the percentages rather than inventing a depth."""
    sb = evaluate(plot_area_sqm=929, road_width_m=12.0)["setbacks"]["value"]
    assert sb["front_percent_of_depth"] == 12.0
    assert sb["rear_percent_of_depth"] == 8.0
    assert sb["side_percent_of_width"] == 8.0
    assert "front_m" not in sb
    assert "depth" in sb["needs"]


def test_above_4000_sqm_is_five_metres_all_sides() -> None:
    sb = evaluate(plot_area_sqm=5000, road_width_m=12.0)["setbacks"]["value"]
    assert sb["front_m"] == sb["rear_m"] == sb["side_m"] == 5.0


def test_setbacks_carry_the_table_9_caveat() -> None:
    """Table 8 only covers buildings up to 12.0 m. Table 9 is not encoded, and a
    user must not assume these figures apply to a taller design."""
    sb = evaluate(plot_area_sqm=200, road_width_m=12.0)["setbacks"]
    joined = " ".join(sb["assumptions"]) + " ".join(sb.get("caveats", []))
    assert "Table 9" in joined
    assert "NOT" in joined


# --- height caps ---------------------------------------------------------


def test_small_plot_height_cap_fires() -> None:
    h = evaluate(plot_area_sqm=120, road_width_m=12.0)["max_height"]
    assert h["value"] == 12.0
    assert h["status"] == "COMPUTED"
    assert "stilt" in " ".join(h["assumptions"]).lower()


def test_narrow_road_height_cap_fires() -> None:
    h = evaluate(plot_area_sqm=1000, road_width_m=6.0)["max_height"]
    assert h["value"] == 15.0
    assert h["status"] == "COMPUTED"


def test_the_stricter_cap_wins_when_both_apply() -> None:
    """A 200 sq.m plot on a 6 m road triggers both. 12.0 m must not be raised
    to 15.0 m by the second rule."""
    h = evaluate(plot_area_sqm=200, road_width_m=6.0)["max_height"]
    assert h["value"] == 12.0


def test_no_height_cap_when_neither_rule_applies() -> None:
    """A large plot on a wide road depends on FAR, which is not encoded."""
    h = evaluate(plot_area_sqm=5000, road_width_m=12.0)["max_height"]
    assert h["value"] is None
    assert h["reason"]


# --- floors follow from a real height ------------------------------------


def test_floors_derive_from_the_statutory_height() -> None:
    d = evaluate(plot_area_sqm=120, road_width_m=12.0)
    assert d["max_height"]["value"] == 12.0
    assert d["potential_floors"]["value"] == 4       # 12.0 / 3.0
    assert d["potential_floors"]["confidence"] <= d["max_height"]["confidence"]


# --- the OCR extraction is kept, and kept honest -------------------------


def test_ocr_output_is_recorded_as_unverified_candidate_text() -> None:
    import json

    path = (Path(__file__).resolve().parents[2] / "data" / "processed"
            / "zoning_notification_ocr.json")
    if not path.exists():
        pytest.skip("OCR extraction not run")
    d = json.loads(path.read_text(encoding="utf-8"))
    assert "NOT VERIFIED" in d["status"]
    joined = " ".join(d["caveats"])
    assert "MISREADS DIGITS" in joined
    assert "NOTHING HERE IS ENCODED" in joined
