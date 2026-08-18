"""District and taluk coverage for both cities.

Two layers answer overlapping questions and the precedence between them is the
design:

    administrative boundary (T3, areal, complete)  -> district, taluk
    revenue sheet           (T2, cadastral, partial) -> + hobli, village, survey

The failure this guards against is the tempting one: now that a polygon layer
covers the whole city, letting it appear to answer the cadastral questions too.
A boundary cannot produce a survey number, and widening areal coverage must not
quietly widen what the platform claims to know about a parcel.
"""

from __future__ import annotations

import pytest

from app.facts import Status
from app.services import admin_boundaries, jurisdiction

# Inside a published revenue sheet — the cadastral layer should win here.
IN_SHEET = (77.6974, 12.9591)          # Marathahalli
# Inside Bengaluru but outside every revenue sheet.
OUT_OF_SHEET = (77.5833, 12.9250)      # Jayanagar
CHENNAI = (80.2341, 13.0418)           # T Nagar


def _needs(city: str) -> None:
    if not admin_boundaries.is_available(city):
        pytest.skip(f"{city} boundary layer not ingested")


def _facts(lng: float, lat: float, city: str) -> dict:
    return jurisdiction.jurisdiction(lng, lat, city).facts


# --- the coverage the user actually asked for ---------------------------


def test_taluk_resolves_outside_the_revenue_sheets() -> None:
    """The whole point of adding this layer."""
    _needs("bengaluru")
    f = _facts(*OUT_OF_SHEET, "bengaluru")
    assert f["taluk"].value, "taluk still unavailable outside the sheets"
    assert f["district"].value


def test_taluk_resolves_for_chennai() -> None:
    """Chennai previously had no taluk at all."""
    _needs("chennai")
    f = _facts(*CHENNAI, "chennai")
    assert f["taluk"].value
    assert f["district"].value


def test_both_cities_have_many_taluks_not_a_handful() -> None:
    for city, minimum in (("bengaluru", 10), ("chennai", 10)):
        _needs(city)
        cov = admin_boundaries.coverage(city)
        assert cov["taluk_count"] >= minimum, f"{city} only {cov['taluk_count']}"
        assert cov["districts"]


# --- precedence between the two layers ----------------------------------


def test_revenue_sheet_wins_where_it_covers_the_point() -> None:
    """A T2 cadastral value must not be replaced by a T3 areal one."""
    _needs("bengaluru")
    f = _facts(*IN_SHEET, "bengaluru")
    assert f["taluk"].status is Status.VERIFIED
    assert f["taluk"].value == "Bangalore East"


def test_boundary_value_is_indicative_never_verified() -> None:
    """Republished, undated boundaries cannot carry a VERIFIED status."""
    _needs("bengaluru")
    f = _facts(*OUT_OF_SHEET, "bengaluru")
    assert f["taluk"].status is Status.INDICATIVE
    assert f["taluk"].status is not Status.VERIFIED
    joined = " ".join(f["taluk"].caveats)
    assert "not the issuing authority" in joined
    assert "reorganised taluks" in joined


# --- what the new layer must NOT do -------------------------------------


def test_boundary_layer_never_supplies_a_survey_number() -> None:
    """The failure mode this whole module is arranged to prevent."""
    _needs("bengaluru")
    f = _facts(*OUT_OF_SHEET, "bengaluru")
    for key in ("hobli", "village", "survey_number"):
        assert f[key].status is Status.UNAVAILABLE
        assert f[key].value is None
        assert "cannot produce" in f[key].reason


def test_chennai_still_has_no_cadastral_fields() -> None:
    _needs("chennai")
    f = _facts(*CHENNAI, "chennai")
    for key in ("hobli", "village", "survey_number"):
        assert f[key].status is Status.UNAVAILABLE
        assert f[key].value is None


def test_cadastral_fields_survive_inside_a_sheet() -> None:
    """Widening areal coverage must not have broken the cadastral path."""
    _needs("bengaluru")
    f = _facts(*IN_SHEET, "bengaluru")
    assert f["hobli"].value == "Varthur"
    assert f["village"].value
    assert f["survey_number"].status is Status.INDICATIVE


# --- coverage is reported per layer, not as one blurred number ----------


def test_coverage_separates_areal_from_cadastral() -> None:
    _needs("bengaluru")
    from fastapi.testclient import TestClient

    from app.main import app

    d = TestClient(app).get("/api/v1/jurisdiction/coverage",
                            params={"city": "bengaluru"}).json()
    assert d["administrative_layer"]["areal_coverage"].startswith("COMPLETE")
    assert d["cadastral_layer"]["areal_coverage"].startswith("PARTIAL")
    assert "no polygon layer can produce them" in d["read_this_first"]


def test_chennai_coverage_declares_the_cadastral_gap() -> None:
    _needs("chennai")
    from fastapi.testclient import TestClient

    from app.main import app

    d = TestClient(app).get("/api/v1/jurisdiction/coverage",
                            params={"city": "chennai"}).json()
    assert d["cadastral_layer"]["available"] is False
    assert d["cadastral_layer"]["areal_coverage"] == "NONE"
    assert d["administrative_layer"]["available"] is True


def test_point_far_outside_returns_nothing() -> None:
    _needs("bengaluru")
    assert admin_boundaries.locate(72.87, 19.07, "bengaluru") is None   # Mumbai
