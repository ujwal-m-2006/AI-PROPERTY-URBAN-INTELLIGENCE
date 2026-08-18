"""Fact framework — provenance and confidence for every user-facing value."""

from app.facts.confidence import (
    Category,
    CategoryScore,
    ConfidenceReport,
    build_report,
    completeness,
    recency_decay,
    score,
    score_category,
)
from app.facts.types import (
    METHOD_FACTOR,
    TIER_CEILING,
    Candidate,
    Fact,
    Method,
    SourceRef,
    Status,
    Tier,
)

__all__ = [
    "METHOD_FACTOR",
    "TIER_CEILING",
    "Candidate",
    "Category",
    "CategoryScore",
    "ConfidenceReport",
    "Fact",
    "Method",
    "SourceRef",
    "Status",
    "Tier",
    "build_report",
    "completeness",
    "recency_decay",
    "score",
    "score_category",
]
