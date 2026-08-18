"""Local-language ward names, in both cities.

Bengaluru showed a Kannada name on all 369 wards. Chennai showed none on any of
its 200 — not because the data was missing, but because the ward ingest matched
each ward to an OpenStreetMap locality, took `name`, and threw the rest of the
record away. The Tamil name was sitting in `name_local` the whole time.

Two rules this file pins:

  * **Both cities get a local name where one exists.** A parity test catches
    "Chennai has none at all", which is what the bug looked like.
  * **Nothing is transliterated to fill the gap.** OSM carries `name:ta` for
    some localities and not others. A machine-made Tamil spelling of an English
    name is not a Tamil name, so absent stays absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PROCESSED = Path(__file__).resolve().parents[2] / "data" / "processed"


def wards(city: str) -> list[dict]:
    r = client.get("/api/v1/jurisdiction/wards", params={"city": city})
    assert r.status_code == 200
    d = r.json()
    return d if isinstance(d, list) else d["data"]


def _layer(name: str) -> list[dict]:
    path = PROCESSED / name
    if not path.exists():
        pytest.skip(f"{name} not ingested")
    return [f["properties"]
            for f in json.loads(path.read_text(encoding="utf-8"))["features"]]


# --- the bug ------------------------------------------------------------


def test_chennai_wards_have_tamil_names() -> None:
    """The regression itself: every Chennai ward had ward_name_kn = None."""
    have = [w for w in wards("chennai") if w.get("ward_name_kn")]
    assert have, "no Chennai ward carries a local-language name"
    assert len(have) >= 100, f"only {len(have)}/200 — the join has regressed"


def test_tamil_names_are_actually_tamil_script() -> None:
    """A Latin string in the local field would mean the join picked `name`."""
    for w in wards("chennai"):
        local = w.get("ward_name_kn")
        if not local:
            continue
        assert any("஀" <= ch <= "௿" for ch in local), (
            f"ward {w['ward_no']} local name {local!r} contains no Tamil script"
        )


def test_both_cities_carry_local_names() -> None:
    """Parity — the failure mode was one city having none at all."""
    for city, minimum in (("bengaluru", 300), ("chennai", 100)):
        have = [w for w in wards(city) if w.get("ward_name_kn")]
        assert len(have) >= minimum, f"{city}: only {len(have)} local names"


# --- and the honesty around it ------------------------------------------


def test_missing_tamil_names_are_left_null_not_transliterated() -> None:
    """OSM has no name:ta for every locality. Absent must stay absent."""
    props = _layer("chennai_wards.geojson")
    missing = [p for p in props if not p.get("ward_name_local")]
    assert missing, (
        "every ward has a Tamil name — if a transliteration step was added, "
        "these are machine-made spellings, not Tamil names"
    )
    for p in missing:
        assert p.get("ward_name_local") is None
        assert p.get("ward_name_local_lang") is None


def test_local_name_is_labelled_derived_not_official() -> None:
    props = _layer("chennai_wards.geojson")
    localised = [p for p in props if p.get("ward_name_local")]
    assert localised
    for p in localised:
        src = p.get("ward_name_local_source") or ""
        assert "DERIVED" in src
        assert "not an official" in src.lower()
        assert p.get("ward_name_local_lang") == "ta"


def test_english_and_local_names_describe_the_same_place() -> None:
    """The join may choose among containing localities, never mix two."""
    props = _layer("chennai_wards.geojson")
    for p in props:
        if p.get("place_name_local"):
            assert p.get("place_name"), (
                f"ward {p.get('ward_no')} has a local place name but no English "
                "one — the two came from different records"
            )
            assert p["place_name_local"] in (p.get("ward_name_local") or "")


def test_bengaluru_local_names_are_kannada_not_tamil() -> None:
    """Guards against a copy-paste that points both cities at one gazetteer."""
    for w in wards("bengaluru")[:40]:
        local = w.get("ward_name_kn")
        if not local:
            continue
        assert any("ಀ" <= ch <= "೿" for ch in local), (
            f"Bengaluru ward {w['ward_no']} local name {local!r} is not Kannada"
        )


# --- the UI must use them -----------------------------------------------


def _frontend() -> str:
    html = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    if not html.exists():
        pytest.skip("frontend not present")
    return html.read_text(encoding="utf-8")


def test_ward_search_indexes_the_local_name() -> None:
    """Typing எண்ணூர் must find the ward, not nothing."""
    html = _frontend()
    assert "wardIndex[local.toLowerCase()] = w" in html
    assert "const bare = local.replace(" in html


def test_map_label_shows_the_local_name() -> None:
    html = _frontend()
    assert "const localName = f.properties.ward_name_kn" in html


def test_local_name_styling_is_not_kannada_specific() -> None:
    """The `.kn` class is shared by both cities; it must be styling only."""
    html = _frontend()
    idx = html.find(".kn{")
    assert idx != -1
    rule = html[idx:html.index("}", idx)]
    assert "font-family" not in rule, (
        "the shared local-name class sets a font-family, which would render "
        "one city's script with the other's font"
    )
