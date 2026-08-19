"""Does the finding survive changing the method?

Two unsupervised results were reported on the strength of one number each: k
chosen by silhouette, and anomalies found by Isolation Forest. Both look like
findings until a second method is asked the same question.

CLUSTERING — three indices, and they do not agree
    Silhouette, Davies-Bouldin and Calinski-Harabasz choose different k in
    every clustering this project runs. k is therefore a modelling choice, and
    the tab must say so rather than presenting one index's optimum as the
    number of ward types.

ANOMALIES — three detectors, and they overlap almost not at all
    Isolation Forest, LOF and DBSCAN get identical rows, identical features and
    an identical 5% budget. On Bengaluru they agree on 10 of the 1,341 rows any
    of them flags. "Anomalous" is a property of the detector here, and these
    tests exist to stop that being smoothed over later.

The tests assert the honesty, not the numbers. A future dataset could make the
indices agree — that is allowed. What is not allowed is claiming agreement
without measuring it, or letting a weak clustering be used to classify a ward.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ARTIFACTS = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
CITIES = ("bengaluru", "chennai")
INDICES = {"silhouette", "davies_bouldin", "calinski_harabasz"}


def artifact(city: str, name: str) -> dict:
    path = ARTIFACTS / city / name
    if not path.exists():
        pytest.skip(f"{name} not built for {city}")
    return json.loads(path.read_text(encoding="utf-8"))


# --- cluster validity ------------------------------------------------------

@pytest.mark.parametrize("city", CITIES)
def test_ward_typologies_are_scored_by_three_indices(city: str) -> None:
    t = artifact(city, "planning_models.json").get("ward_typology", {})
    if not t.get("available"):
        pytest.skip("typologies not computed")
    assert set(t["chosen_k_by_index"]) == INDICES
    for scores in t["validity_by_k"].values():
        assert set(scores) == INDICES


@pytest.mark.parametrize("city", CITIES)
def test_index_disagreement_is_reported_not_hidden(city: str) -> None:
    """If the three indices pick different k, the note must say so."""
    t = artifact(city, "planning_models.json").get("ward_typology", {})
    if not t.get("available"):
        pytest.skip("typologies not computed")
    picks = set(t["chosen_k_by_index"].values())
    assert t["indices_agree_on_k"] is (len(picks) == 1)
    if not t["indices_agree_on_k"]:
        assert "DIFFERENT k" in t["validity_note"]


@pytest.mark.parametrize("city", CITIES)
def test_silhouette_still_decides_k(city: str) -> None:
    """Adding indices must not silently change the published k."""
    t = artifact(city, "planning_models.json").get("ward_typology", {})
    if not t.get("available"):
        pytest.skip("typologies not computed")
    assert t["k"] == t["chosen_k_by_index"]["silhouette"]
    assert t["silhouette"] == t["validity_by_k"][str(t["k"])]["silhouette"]


@pytest.mark.parametrize("city", CITIES)
def test_weak_or_disputed_clusters_may_not_classify_a_ward(city: str) -> None:
    """Two independent grounds for refusal, and either is enough.

    A ward typology that is weakly separated OR whose k depends on the index is
    not a category system. Letting it be used as one would hand a planner
    groups the data does not support.
    """
    r = client.get("/api/v1/planning-ml/typology", params={"city": city})
    assert r.status_code == 200
    d = r.json()
    if not d.get("available"):
        pytest.skip("typologies not computed")
    expected = bool(d["well_separated"]) and bool(d["indices_agree_on_k"])
    assert d["usable_for_classification"] is expected
    if not expected:
        assert d["usable_for_classification"] is False


def test_locality_clustering_records_the_same_three_indices() -> None:
    cu = artifact("bengaluru", "extra_models.json").get("clustering", {})
    if not cu.get("available"):
        pytest.skip("locality clustering not computed")
    assert set(cu["chosen_k_by_index"]) == INDICES
    assert cu["indices_agree_on_k"] is (len(set(cu["chosen_k_by_index"].values())) == 1)


# --- anomaly detector agreement -------------------------------------------

@pytest.mark.parametrize("city", CITIES)
def test_three_detectors_are_run_on_the_same_budget(city: str) -> None:
    """Otherwise the comparison measures flag rate, not flag agreement."""
    an = artifact(city, "extra_models.json")["anomaly"]
    dets = an["detectors"]
    assert set(dets) == {"isolation_forest", "lof", "dbscan"}
    total = an["total"]
    for name, d in dets.items():
        share = d["flagged"] / total
        assert share <= 0.12, f"{name} flagged {share:.1%}, far off the 5% budget"


@pytest.mark.parametrize("city", CITIES)
def test_agreement_is_measured_by_jaccard_not_raw_overlap(city: str) -> None:
    """With three detectors each flagging 5%, ~90% of rows are agreed by default.

    Reporting that as agreement would be arithmetic dressed as a result.
    """
    ag = artifact(city, "extra_models.json")["anomaly"]["agreement"]
    assert len(ag["pairwise"]) == 3
    for pair in ag["pairwise"].values():
        assert 0.0 <= pair["jaccard"] <= 1.0
    assert ag["flagged_by_all"] <= ag["flagged_by_any"]


@pytest.mark.parametrize("city", CITIES)
def test_the_disagreement_is_stated_where_a_reader_will_see_it(city: str) -> None:
    an = artifact(city, "extra_models.json")["anomaly"]
    assert "property of the detector" in an["agreement_note"] or \
           "about that detector" in an["agreement_note"]
    # And the existing caveat must survive: the 5% is an assumption.
    assert "assumption" in an["caveat"]


@pytest.mark.parametrize("city", CITIES)
def test_no_flag_is_ever_presented_as_a_finding(city: str) -> None:
    """The platform's position on anomalies, asserted rather than assumed."""
    an = artifact(city, "extra_models.json")["anomaly"]
    assert "not evidence of anything wrong" in an["caveat"]


def test_frontend_shows_the_detector_disagreement() -> None:
    html = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    if not html.exists():
        pytest.skip("frontend not present")
    text = html.read_text(encoding="utf-8")
    assert "Do three detectors flag the same rows?" in text
    assert "The detectors barely" in text
    assert "Three validity indices" in text
