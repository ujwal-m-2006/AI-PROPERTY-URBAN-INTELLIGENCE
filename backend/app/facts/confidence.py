"""The confidence engine.

    confidence = tier_ceiling
               x completeness(inputs)
               x recency_decay(source_updated, half_life)
               x method_factor
               x (1 - conflict_penalty)

The one design decision worth defending: category and overall scores use the
MINIMUM, not the mean. A report with perfect ward data and no record data is not
"75% confident" — it is unverified on records, and averaging hides precisely the
thing a buyer needs to see.
"""

from __future__ import annotations

import enum
import math
from datetime import date
from typing import Any, Iterable

from pydantic import BaseModel, Field

from app.facts.types import METHOD_FACTOR, TIER_CEILING, Fact, Method, Status, Tier


class Category(enum.StrEnum):
    """Report sections that get their own confidence score."""

    JURISDICTION = "jurisdiction"
    PLANNING = "planning"
    RECORDS = "records"
    INFRASTRUCTURE = "infrastructure"
    RISK = "risk"
    MARKET = "market"


HALF_LIFE_DAYS: dict[Category, float] = {
    # How fast our trust in a stale value should decay, per layer.
    # Boundaries change rarely but consequentially; market data goes off fast.
    Category.JURISDICTION: 3 * 365.0,
    Category.PLANNING: 2 * 365.0,
    Category.RECORDS: 365.0,
    Category.INFRASTRUCTURE: 545.0,
    Category.RISK: 730.0,
    Category.MARKET: 120.0,
}

RECENCY_FLOOR = 0.40
"""Age alone never drives confidence below this. Old official data still beats
having nothing, and a hard floor keeps a stale-but-real source above a guess."""


def recency_decay(
    source_updated: date | None,
    category: Category,
    *,
    today: date | None = None,
) -> float:
    """Exponential decay on source age, floored.

    An unknown update date is treated as a real penalty rather than as fresh —
    not knowing when something was last updated is itself information.
    """
    if source_updated is None:
        return 0.80

    today = today or date.today()
    age_days = max((today - source_updated).days, 0)
    half_life = HALF_LIFE_DAYS[category]
    decayed = math.pow(0.5, age_days / half_life)
    return max(decayed, RECENCY_FLOOR)


def completeness(required: Iterable[str], present: Iterable[str]) -> float:
    """Fraction of the inputs a calculation wanted that it actually got."""
    required_set = set(required)
    if not required_set:
        return 1.0
    return len(required_set & set(present)) / len(required_set)


def score(
    *,
    tier: Tier,
    category: Category,
    method: Method = Method.EXACT_MATCH,
    source_updated: date | None = None,
    completeness_ratio: float = 1.0,
    conflict_penalty: float = 0.0,
    today: date | None = None,
) -> float:
    """Compute a confidence score from its components."""
    if not 0.0 <= completeness_ratio <= 1.0:
        raise ValueError("completeness_ratio must be in [0, 1]")
    if not 0.0 <= conflict_penalty <= 1.0:
        raise ValueError("conflict_penalty must be in [0, 1]")

    value = (
        TIER_CEILING[tier]
        * completeness_ratio
        * recency_decay(source_updated, category, today=today)
        * METHOD_FACTOR[method]
        * (1.0 - conflict_penalty)
    )
    return round(min(value, TIER_CEILING[tier]), 4)


class CategoryScore(BaseModel):
    category: Category
    confidence: float = Field(ge=0.0, le=1.0)
    known: int
    total: int
    unavailable_fields: list[str] = Field(default_factory=list)
    conflicted_fields: list[str] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.known / self.total if self.total else 0.0


class ConfidenceReport(BaseModel):
    """The aggregate shown at the top of a 360 report."""

    overall: float = Field(ge=0.0, le=1.0)
    categories: dict[Category, CategoryScore]
    blocking_unknowns: list[str] = Field(default_factory=list)

    @property
    def weakest(self) -> Category | None:
        scored = [c for c in self.categories.values() if c.total]
        if not scored:
            return None
        return min(scored, key=lambda c: c.confidence).category


def score_category(
    category: Category,
    fields: dict[str, Fact[Any]],
) -> CategoryScore:
    """Score one report section.

    An empty or fully-unavailable category scores 0.0. It does not score 1.0 for
    having no problems, which is the trap in every naive averaging scheme.
    """
    unavailable = [k for k, f in fields.items() if f.status is Status.UNAVAILABLE]
    conflicted = [k for k, f in fields.items() if f.status is Status.CONFLICT]
    known = [f for f in fields.values() if f.is_known]

    confidence = min((f.confidence for f in known), default=0.0)

    # A category that is mostly holes should not inherit the confidence of its
    # one good field. Scale by coverage.
    if fields:
        confidence *= len(known) / len(fields)

    return CategoryScore(
        category=category,
        confidence=round(confidence, 4),
        known=len(known),
        total=len(fields),
        unavailable_fields=sorted(unavailable),
        conflicted_fields=sorted(conflicted),
    )


def build_report(
    sections: dict[Category, dict[str, Fact[Any]]],
    *,
    blocking_unknowns: list[str] | None = None,
) -> ConfidenceReport:
    """Assemble the overall confidence report.

    Overall is the minimum across populated categories — see module docstring.
    """
    scores = {cat: score_category(cat, fields) for cat, fields in sections.items()}
    populated = [s for s in scores.values() if s.total]
    overall = min((s.confidence for s in populated), default=0.0)

    derived_blockers = sorted(
        {
            f"{cat.value}.{field}"
            for cat, s in scores.items()
            for field in s.unavailable_fields + s.conflicted_fields
        }
    )

    return ConfidenceReport(
        overall=round(overall, 4),
        categories=scores,
        blocking_unknowns=(blocking_unknowns or []) + derived_blockers,
    )
