"""The Administrative Jurisdiction tab must show everything the API returns.

`corporation_kn` was returned by the API for months and never rendered — the
Kannada corporation name was silently dropped while the ward's local name was
shown. Nothing failed; the field simply wasn't in any display list.

That is the failure mode this file exists to catch. A fact the backend computes,
sources and attaches provenance to, and then the UI quietly discards, is worse
than one that was never computed: the provenance work is done and thrown away,
and no test notices.

These tests parse the frontend's field lists out of index.html and compare them
against a live API response.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "index.html"

# Fields the tab deliberately does not list as rows.
INTENTIONALLY_NOT_LISTED: set[str] = set()

POINTS = {
    "bengaluru": (12.9591, 77.6974),   # inside a revenue sheet
    "chennai": (13.0418, 80.2341),
}


def _html() -> str:
    if not FRONTEND.exists():
        pytest.skip("frontend not present")
    return FRONTEND.read_text(encoding="utf-8")


def _list(name: str) -> list[str]:
    """Pull a `const NAME = [...]` field list out of the frontend."""
    m = re.search(rf"const {name} = \[(.*?)\];", _html(), re.S)
    if not m:
        pytest.fail(f"frontend has no `const {name} = [...]` list")
    return re.findall(r'"([a-z_0-9]+)"', m.group(1))


DISPLAY_LISTS = ("CORE", "AUTHORITY", "REVENUE", "ROAD", "ENVIRONMENT", "GAPS")


def _displayed() -> set[str]:
    return {key for name in DISPLAY_LISTS for key in _list(name)}


def _api_keys(city: str) -> set[str]:
    lat, lng = POINTS[city]
    r = client.get("/api/v1/jurisdiction",
                   params={"lat": lat, "lng": lng, "city": city})
    assert r.status_code == 200
    return set(r.json()["data"])


# --- nothing computed may be silently dropped ---------------------------


@pytest.mark.parametrize("city", ["bengaluru", "chennai"])
def test_every_api_field_is_displayed_somewhere(city: str) -> None:
    missing = _api_keys(city) - _displayed() - INTENTIONALLY_NOT_LISTED
    assert not missing, (
        f"{city}: the API returns {sorted(missing)} but no display list "
        "includes them, so the tab drops them silently"
    )


@pytest.mark.parametrize("city", ["bengaluru", "chennai"])
def test_no_display_list_references_a_field_the_api_never_sends(city: str) -> None:
    """The mirror image — a listed field that never arrives renders nothing."""
    stale = _displayed() - _api_keys(city)
    # population only appears for Bengaluru; allow per-city absence of that one.
    stale.discard("population")
    assert not stale, f"{city}: display lists reference absent fields {sorted(stale)}"


# --- every section must actually carry content --------------------------


def test_each_field_list_is_non_empty() -> None:
    """An empty list produces a titled section with no rows, which reads as broken."""
    for name in DISPLAY_LISTS:
        assert _list(name), f"{name} is empty — its section would render blank"


def test_revenue_section_renders_its_own_rows() -> None:
    """This section previously had a heading and prose but no data."""
    html = _html()
    m = re.search(r"Revenue &amp; administrative jurisdiction</h2>(.{0,200})", html, re.S)
    assert m, "revenue section not found"
    assert "rows(REVENUE, d)" in m.group(1), (
        "the revenue section does not render a rows() table, so it would show "
        "a heading with no data"
    )


def test_the_two_layers_are_not_merged_into_one_list() -> None:
    """Grouping by source layer is what makes the coverage story legible."""
    core, revenue = set(_list("CORE")), set(_list("REVENUE"))
    assert not (core & revenue), "a field appears in both CORE and REVENUE"
    assert {"district", "taluk"} <= revenue
    assert {"hobli", "village", "survey_number"} <= revenue
    assert "corporation" in core
    # planning_authority left GAPS when it became answerable inside limits.
    assert "planning_authority" in _list("AUTHORITY")
    assert "planning_authority" not in _list("GAPS")


def test_local_language_names_are_displayed() -> None:
    """Both the corporation and the ward carry a local-language name."""
    core = _list("CORE")
    assert "corporation_kn" in core, "the local corporation name is not displayed"
    assert "ward_name_kn" in core


# --- the tab must survive a point outside the city ----------------------


def test_point_outside_gba_still_returns_a_renderable_answer() -> None:
    r = client.get("/api/v1/jurisdiction",
                   params={"lat": 13.30, "lng": 77.30, "city": "bengaluru"})
    d = r.json()
    assert r.status_code == 200
    assert d["found"] is False
    # Every returned fact must carry a reason, or the tab shows blank cells.
    for key, fact in d["data"].items():
        assert fact["value"] is None, f"{key} has a value despite found=False"
        assert fact["reason"], f"{key} is unavailable with no reason to display"


# --- no section may render as a bare heading ----------------------------


@pytest.mark.parametrize("city", ["bengaluru", "chennai"])
def test_every_display_list_yields_at_least_one_row(city: str) -> None:
    """Chennai's "Requested — no data source" section rendered a heading with
    nothing under it, because `population` was returned for Bengaluru only.

    A titled section with no rows reads as a broken panel, so either the field
    must be returned for both cities or the section must drop itself.
    """
    keys = _api_keys(city)
    for name in DISPLAY_LISTS:
        listed = set(_list(name))
        assert listed & keys, (
            f"{city}: display list {name} matches no field the API returns, so "
            "its section renders as a bare heading"
        )


def test_frontend_can_drop_an_empty_section() -> None:
    """The general guard, so this class of bug cannot recur silently."""
    html = _html()
    assert "function hasRows(" in html
    assert "function section(" in html
    assert 'if (!hasRows(keys, data)) return "";' in html


@pytest.mark.parametrize("city", ["bengaluru", "chennai"])
def test_ward_population_is_refused_with_a_city_specific_reason(city: str) -> None:
    """Withheld in both cities, for different reasons — and both are stated."""
    lat, lng = POINTS[city]
    d = client.get("/api/v1/jurisdiction",
                   params={"lat": lat, "lng": lng, "city": city}).json()
    pop = d["data"]["population"]
    assert pop["value"] is None
    reason = pop["reason"]
    assert reason
    if city == "bengaluru":
        assert "6x" in reason and "not provenance" in reason
    else:
        assert "no population field" in reason
        assert "not estimated" in reason or "No figure is estimated" in reason
