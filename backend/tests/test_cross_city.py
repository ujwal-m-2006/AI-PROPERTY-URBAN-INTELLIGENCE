"""Cross-city transfer — the experiment the project was missing.

Transfer was impossible until the schemas were harmonised: of every column in
the two datasets, exactly one name matched. That is a naming problem, not a
research finding, and fixing it unblocked the experiment.

The result is negative in both directions, and the tests below exist to keep it
honestly negative. The tempting error is to report the combined model's higher
R² as evidence that pooling cities helps — it is not. Pooling asking prices with
recorded sale prices widens the variance R² is scored against, and MAE, which is
in rupees and immune to that, barely moves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ARTIFACT = (Path(__file__).resolve().parents[2] / "ml" / "artifacts"
            / "bengaluru" / "cross_city.json")


def payload() -> dict:
    if not ARTIFACT.exists():
        pytest.skip("cross-city experiments not run")
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def api() -> dict:
    r = client.get("/api/v1/cross-city")
    if r.status_code != 200:
        pytest.skip("cross-city unavailable")
    return r.json()


# --- the schema that unblocked it ---------------------------------------


def test_the_shared_vocabulary_is_substantial() -> None:
    sc = client.get("/api/v1/cross-city/schema").json()
    assert sc["shared_feature_count"] >= 15
    # Most of the shared space is urban context, which is the point.
    assert len(sc["gis_features"]) >= 10


def test_every_property_mapping_states_its_claim() -> None:
    """A rename hides an equivalence assertion. Each one must be reviewable."""
    sc = client.get("/api/v1/cross-city/schema").json()
    for f in sc["property_features"]:
        assert f["bengaluru"] and f["chennai"]
        assert len(f["claim"]) > 30, f"{f['shared']} has no stated claim"


def test_incompatible_columns_are_recorded_as_not_mapped() -> None:
    """area_type and BUILDTYPE are both categorical and mean different things.
    Forcing them together would inject a false equivalence."""
    sc = client.get("/api/v1/cross-city/schema").json()
    joined = " ".join(sc["not_mapped"].keys()).lower()
    assert "buildtype" in joined
    assert "property_age_years" in joined or "sale_year" in joined


def test_the_target_mismatch_is_stated_not_buried() -> None:
    sc = client.get("/api/v1/cross-city/schema").json()
    w = sc["target_warning"]
    assert "ASKING" in w and "RECORDED SALE" in w
    assert "does NOT" in w or "not" in w.lower()


# --- the four experiments ------------------------------------------------


def test_all_four_experiments_ran() -> None:
    d = api()
    assert len(d["within_city"]) == 2
    assert len(d["transfer"]) == 2


def test_within_city_uses_spatial_validation() -> None:
    """Otherwise the baseline is inflated and the transfer gap is overstated."""
    for w in payload()["within_city"]:
        assert "GroupKFold" in w["validation"]
        assert "ward" in w["validation"] or "locality" in w["validation"]


def test_transfer_is_scored_both_raw_and_by_rank() -> None:
    """Raw alone would attribute the target mismatch to the model."""
    for t in payload()["transfer"]:
        assert "raw" in t and "rank" in t
        assert t["rank"]["spearman"] is not None
        assert "mismatch" in t["raw"]["reading"]
        assert "percentile" in t["rank"]["reading"]


def test_transfer_is_reported_as_failing() -> None:
    """The measured result. If this ever passes trivially, re-read the numbers
    rather than assuming the models improved."""
    d = api()
    rhos = d["headline"]["rank_spearman"]
    assert all(abs(r) < 0.25 for r in rhos), (
        f"rank transfer Spearman {rhos} — if transfer now works, the finding "
        "text and the README both need rewriting"
    )
    assert d["headline"]["transfer_fails_even_on_rank"] is True


def test_within_city_beats_transfer_substantially() -> None:
    """The comparison that makes the negative result meaningful."""
    d = payload()
    within = [w["spearman"] for w in d["within_city"]]
    across = [t["rank"]["spearman"] for t in d["transfer"]]
    assert min(within) > max(across) + 0.2


# --- the combined model must not be oversold -----------------------------


def test_combined_model_gain_is_identified_as_variance_inflation() -> None:
    """R² rose ~0.09 while MAE moved ~10 rupees. Reporting the R² alone would
    be the single most misleading number available in this project."""
    c = payload()["separate_vs_combined"]
    assert c["r2_gain"] > 0
    # MAE barely moved, so the R² gain is not skill.
    assert abs(c["mae_change"]) < 100
    assert "variance" in c["verdict"].lower()
    assert "not better" in c["verdict"].lower()


def test_combined_comparison_carries_its_caveat() -> None:
    c = payload()["separate_vs_combined"]
    assert "two different targets" in c["caveat"]
    assert "NOT evidence" in c["caveat"]


def test_mae_is_reported_alongside_every_r2() -> None:
    """R² across pooled targets is the trap; MAE is the check on it."""
    c = payload()["separate_vs_combined"]
    for key in ("separate_weighted_mae", "combined_mae",
                "combined_with_city_flag_mae"):
        assert c[key] > 0


# --- the tab shows the negatives ----------------------------------------


def test_frontend_tab_renders_the_negative_results() -> None:
    html = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    if not html.exists():
        pytest.skip("frontend not present")
    text = html.read_text(encoding="utf-8")
    assert 'data-tab="crosscity"' in text
    assert "function renderCrossCity(" in text
    assert "separate_weighted_mae" in text
    assert "target_warning" in text
