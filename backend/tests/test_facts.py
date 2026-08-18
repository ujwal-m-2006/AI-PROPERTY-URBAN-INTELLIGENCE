"""Tests for the Fact framework.

These are the tests that stop the platform fabricating. If one of them starts
failing, something has learned to invent a value.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.facts import (
    Candidate,
    Category,
    Fact,
    Method,
    SourceRef,
    Status,
    Tier,
    build_report,
    recency_decay,
    score,
    score_category,
)


@pytest.fixture
def gba_source() -> SourceRef:
    return SourceRef(
        source_id=uuid4(),
        name="GBA Final Wards Delimitation 2025",
        organisation="Greater Bengaluru Authority",
        source_url="https://data.opencity.in/dataset/gba-wards-delimitation-2025",
        tier=Tier.T2,
        source_updated=date(2025, 12, 1),
    )


@pytest.fixture
def listing_source() -> SourceRef:
    return SourceRef(source_id=uuid4(), name="Listing aggregate", tier=Tier.T4)


# --- the honest default --------------------------------------------------


def test_unavailable_carries_no_value_and_zero_confidence() -> None:
    f: Fact[float] = Fact.unavailable("No verified FAR clause for this zone")
    assert f.value is None
    assert f.confidence == 0.0
    assert f.colour == "GREY"
    assert not f.is_known
    assert "FAR" in (f.reason or "")


def test_unavailable_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="must state a reason"):
        Fact(status=Status.UNAVAILABLE, tier=Tier.T5, confidence=0.0)


def test_unavailable_cannot_smuggle_a_value() -> None:
    with pytest.raises(ValidationError, match="must not carry a value"):
        Fact(
            value=3.0,
            status=Status.UNAVAILABLE,
            tier=Tier.T5,
            confidence=0.0,
            reason="missing",
        )


def test_known_status_requires_a_value() -> None:
    with pytest.raises(ValidationError, match="requires a value"):
        Fact(status=Status.VERIFIED, tier=Tier.T1, confidence=0.9)


# --- provenance rules ----------------------------------------------------


def test_verified_requires_official_tier(listing_source: SourceRef) -> None:
    with pytest.raises(ValidationError, match="only T1/T2"):
        Fact.observed(
            12000.0, source=listing_source, confidence=0.5, status=Status.VERIFIED
        )


def test_verified_requires_a_source() -> None:
    with pytest.raises(ValidationError, match="must cite a source"):
        Fact(value="Bengaluru East", status=Status.VERIFIED, tier=Tier.T1, confidence=0.9)


def test_confidence_is_capped_at_tier_ceiling(gba_source: SourceRef) -> None:
    f = Fact.observed("Ward 42", source=gba_source, confidence=0.99)
    assert f.confidence == 0.85  # T2 ceiling, not the 0.99 asked for


def test_constructing_above_ceiling_directly_is_rejected(gba_source: SourceRef) -> None:
    with pytest.raises(ValidationError, match="exceeds"):
        Fact(
            value="Ward 42",
            status=Status.VERIFIED,
            tier=Tier.T2,
            confidence=0.99,
            source=gba_source,
        )


def test_computed_must_declare_assumptions() -> None:
    with pytest.raises(ValidationError, match="must declare their assumptions"):
        Fact(value=15.0, status=Status.COMPUTED, tier=Tier.T5, confidence=0.5)


# --- derivation ----------------------------------------------------------


def test_derived_confidence_cannot_exceed_weakest_input(gba_source: SourceRef) -> None:
    strong = Fact.observed(1000.0, source=gba_source, confidence=0.85, unit="sq.m")
    weak = Fact.observed(
        7.5,
        source=SourceRef(source_id=uuid4(), name="User declared", tier=Tier.T4),
        confidence=0.40,
        unit="m",
        status=Status.INDICATIVE,
    )

    result = Fact.derive(
        15.0,
        inputs=[strong, weak],
        method=Method.RULE_EVALUATION,
        assumptions=["Road width as declared by user (source: ESTIMATED)"],
        unit="m",
    )

    assert result.confidence <= weak.confidence
    assert result.confidence == pytest.approx(0.40 * 0.90)
    assert result.tier is Tier.T5
    assert result.colour == "AMBER"
    assert set(result.derived_from) == {strong.id, weak.id}


def test_derivation_from_unavailable_input_is_refused(gba_source: SourceRef) -> None:
    known = Fact.observed(1000.0, source=gba_source, confidence=0.85)
    missing: Fact[float] = Fact.unavailable("Road width unknown")

    with pytest.raises(ValueError, match="cannot derive from UNAVAILABLE inputs"):
        Fact.derive(
            15.0,
            inputs=[known, missing],
            method=Method.RULE_EVALUATION,
            assumptions=["something"],
        )


def test_caveats_propagate_through_derivation(gba_source: SourceRef) -> None:
    tainted = Fact.observed(
        1000.0,
        source=gba_source,
        confidence=0.85,
        status=Status.INDICATIVE,
        caveats=["Land use digitised from raster plan; indicative only"],
    )
    result = Fact.derive(
        4000.0,
        inputs=[tainted],
        method=Method.RULE_EVALUATION,
        assumptions=["FAR 4.0 assumed"],
    )
    assert "Land use digitised from raster plan; indicative only" in result.caveats


def test_ml_method_penalises_more_than_exact_match(gba_source: SourceRef) -> None:
    base = Fact.observed(1000.0, source=gba_source, confidence=0.85)
    exact = Fact.derive(
        1.0, inputs=[base], method=Method.EXACT_MATCH, assumptions=["a"]
    )
    predicted = Fact.derive(
        1.0, inputs=[base], method=Method.ML_PREDICTION, assumptions=["a"]
    )
    assert predicted.confidence < exact.confidence


# --- conflict ------------------------------------------------------------


def test_conflict_shows_both_and_resolves_nothing(gba_source: SourceRef) -> None:
    f = Fact.conflict(
        [
            Candidate(value=2400.0, note="Sale deed"),
            Candidate(value=2050.0, source=gba_source, note="GIS parcel"),
        ],
        reason="Document area differs from mapped parcel by more than 10%",
        unit="sq.ft",
    )
    assert f.value is None
    assert f.colour == "RED"
    assert len(f.candidates) == 2


def test_conflict_needs_at_least_two_candidates() -> None:
    with pytest.raises(ValidationError, match="at least two candidates"):
        Fact.conflict([Candidate(value=1.0)], reason="x")


# --- confidence engine ---------------------------------------------------


def test_recency_decay_penalises_age_but_never_below_floor() -> None:
    today = date(2026, 8, 9)
    fresh = recency_decay(today, Category.MARKET, today=today)
    stale = recency_decay(today - timedelta(days=120), Category.MARKET, today=today)
    ancient = recency_decay(today - timedelta(days=5000), Category.MARKET, today=today)

    assert fresh == pytest.approx(1.0)
    assert stale == pytest.approx(0.5, abs=0.01)
    assert ancient == 0.40


def test_unknown_update_date_is_penalised() -> None:
    assert recency_decay(None, Category.JURISDICTION) == 0.80


def test_boundaries_age_more_slowly_than_market_data() -> None:
    today = date(2026, 8, 9)
    a_year_ago = today - timedelta(days=365)
    assert recency_decay(a_year_ago, Category.JURISDICTION, today=today) > recency_decay(
        a_year_ago, Category.MARKET, today=today
    )


def test_score_respects_tier_ceiling() -> None:
    assert score(tier=Tier.T1, category=Category.JURISDICTION) <= 0.95
    assert score(tier=Tier.T4, category=Category.MARKET) <= 0.55


def test_missing_inputs_reduce_score() -> None:
    full = score(tier=Tier.T1, category=Category.PLANNING, completeness_ratio=1.0)
    half = score(tier=Tier.T1, category=Category.PLANNING, completeness_ratio=0.5)
    assert half == pytest.approx(full * 0.5)


# --- aggregation: minimum, not mean --------------------------------------


def test_empty_category_scores_zero_not_one() -> None:
    s = score_category(Category.RECORDS, {})
    assert s.confidence == 0.0
    assert s.coverage == 0.0


def test_category_with_only_holes_scores_zero() -> None:
    s = score_category(
        Category.RECORDS,
        {
            "khata": Fact.unavailable("No public API; upload required"),
            "tax": Fact.unavailable("Portal-only, OTP gated"),
        },
    )
    assert s.confidence == 0.0
    assert s.unavailable_fields == ["khata", "tax"]


def test_overall_is_the_minimum_not_the_mean(gba_source: SourceRef) -> None:
    sections = {
        Category.JURISDICTION: {
            "ward": Fact.observed("Ward 42", source=gba_source, confidence=0.85),
            "corporation": Fact.observed(
                "Bengaluru East", source=gba_source, confidence=0.85
            ),
        },
        Category.RECORDS: {
            "khata": Fact.unavailable("No public API; upload required"),
        },
    }
    report = build_report(sections)

    # Mean would be ~0.43 and would read as "moderately confident overall".
    assert report.overall == 0.0
    assert report.weakest is Category.RECORDS
    assert "records.khata" in report.blocking_unknowns


def test_partial_coverage_scales_category_confidence(gba_source: SourceRef) -> None:
    s = score_category(
        Category.INFRASTRUCTURE,
        {
            "metro_distance": Fact.observed(2100.0, source=gba_source, confidence=0.80),
            "road_width": Fact.unavailable("Not in road-width dataset"),
        },
    )
    # One good field out of two must not carry the whole category.
    assert s.confidence == pytest.approx(0.80 * 0.5)
