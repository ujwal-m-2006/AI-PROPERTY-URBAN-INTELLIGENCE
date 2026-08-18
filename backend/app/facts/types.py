"""The Fact type — the core of the platform.

Nothing user-facing is ever a bare value. Every value carries where it came from,
how confident we are, and what we assumed to produce it.

The invariants below are enforced by validators, not by convention, because the
single failure mode this platform must never have is emitting a number that looks
authoritative and isn't.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Any, Generic, Self, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class Status(enum.StrEnum):
    """What kind of claim this fact is making."""

    VERIFIED = "VERIFIED"
    """Read directly from an official source. GREEN."""

    INDICATIVE = "INDICATIVE"
    """From a real source, but the source is derived, partial or dated. AMBER."""

    COMPUTED = "COMPUTED"
    """We calculated it. Assumptions are mandatory. AMBER."""

    ESTIMATED = "ESTIMATED"
    """A model produced it. Interval is mandatory upstream. AMBER."""

    UNAVAILABLE = "UNAVAILABLE"
    """We do not know. value is None, always. GREY."""

    CONFLICT = "CONFLICT"
    """Sources disagree beyond tolerance. We show both and resolve nothing. RED."""


class Tier(enum.StrEnum):
    """Provenance tier. See docs/01-data-source-audit.md section 0.2."""

    T1 = "T1"  # official primary
    T2 = "T2"  # official secondary (republished)
    T3 = "T3"  # community / open data
    T4 = "T4"  # commercial / listing
    T5 = "T5"  # derived by this platform


TIER_CEILING: dict[Tier, float] = {
    Tier.T1: 0.95,
    Tier.T2: 0.85,
    Tier.T3: 0.70,
    Tier.T4: 0.55,
    Tier.T5: 1.00,  # not a real ceiling: T5 is bounded by its inputs, see derive()
}


class Method(enum.StrEnum):
    """How a derived value was produced. Each carries a confidence multiplier."""

    EXACT_MATCH = "EXACT_MATCH"
    SPATIAL_JOIN = "SPATIAL_JOIN"
    MANUAL_TRANSCRIPTION = "MANUAL_TRANSCRIPTION"
    RULE_EVALUATION = "RULE_EVALUATION"
    OCR_EXTRACTION = "OCR_EXTRACTION"
    GEOREFERENCED = "GEOREFERENCED"
    INTERPOLATION = "INTERPOLATION"
    ML_PREDICTION = "ML_PREDICTION"
    HEURISTIC = "HEURISTIC"


METHOD_FACTOR: dict[Method, float] = {
    Method.EXACT_MATCH: 1.00,
    Method.SPATIAL_JOIN: 0.95,
    Method.MANUAL_TRANSCRIPTION: 0.90,
    Method.RULE_EVALUATION: 0.90,
    Method.OCR_EXTRACTION: 0.75,
    Method.GEOREFERENCED: 0.70,
    Method.INTERPOLATION: 0.75,
    Method.ML_PREDICTION: 0.70,
    Method.HEURISTIC: 0.60,
}


class SourceRef(BaseModel):
    """A pointer to meta.data_sources, denormalised for transport.

    source_url is deliberately optional and must never be invented. A source with
    no public URL says so; it does not get a plausible-looking one.
    """

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    name: str
    organisation: str | None = None
    source_url: str | None = None
    tier: Tier
    retrieved_at: datetime | None = None
    source_updated: date | None = None
    licence: str | None = None


class Candidate(BaseModel, Generic[T]):
    """One side of a CONFLICT. We present these; we do not pick a winner."""

    model_config = ConfigDict(frozen=True)

    value: T
    source: SourceRef | None = None
    note: str | None = None


class Fact(BaseModel, Generic[T]):
    """A single value plus everything needed to judge whether to trust it."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    value: T | None = None
    unit: str | None = None

    status: Status
    tier: Tier
    confidence: float = Field(ge=0.0, le=1.0)

    source: SourceRef | None = None
    valid_as_of: date | None = None
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    reason: str | None = None
    """Why the value is missing. Mandatory when status is UNAVAILABLE."""

    method: Method | None = None
    derived_from: list[UUID] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    candidates: list[Candidate[T]] = Field(default_factory=list)

    # ---- invariants -----------------------------------------------------

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if self.status is Status.UNAVAILABLE:
            if self.value is not None:
                raise ValueError("UNAVAILABLE facts must not carry a value")
            if not self.reason:
                raise ValueError("UNAVAILABLE facts must state a reason")
            if self.confidence != 0.0:
                raise ValueError("UNAVAILABLE facts must have confidence 0.0")

        elif self.status is Status.CONFLICT:
            if len(self.candidates) < 2:
                raise ValueError("CONFLICT facts must carry at least two candidates")
            if self.value is not None:
                raise ValueError(
                    "CONFLICT facts must not resolve to a value; present candidates instead"
                )

        else:
            if self.value is None:
                raise ValueError(
                    f"status {self.status} requires a value; use Fact.unavailable() instead"
                )

        if self.status is Status.COMPUTED and not self.assumptions:
            raise ValueError("COMPUTED facts must declare their assumptions")

        if self.status is Status.VERIFIED:
            if self.tier not in (Tier.T1, Tier.T2):
                raise ValueError("only T1/T2 sources can produce VERIFIED facts")
            if self.source is None:
                raise ValueError("VERIFIED facts must cite a source")

        if self.tier is not Tier.T5:
            ceiling = TIER_CEILING[self.tier]
            if self.confidence > ceiling:
                raise ValueError(
                    f"confidence {self.confidence} exceeds {self.tier} ceiling {ceiling}"
                )

        return self

    # ---- constructors ---------------------------------------------------

    @classmethod
    def unavailable(cls, reason: str, *, unit: str | None = None) -> Fact[T]:
        """The honest default. Used wherever data is missing.

        There is deliberately no way to supply a fallback value here.
        """
        return cls(
            value=None,
            unit=unit,
            status=Status.UNAVAILABLE,
            tier=Tier.T5,
            confidence=0.0,
            reason=reason,
        )

    @classmethod
    def observed(
        cls,
        value: T,
        *,
        source: SourceRef,
        confidence: float,
        unit: str | None = None,
        status: Status = Status.VERIFIED,
        valid_as_of: date | None = None,
        caveats: list[str] | None = None,
    ) -> Fact[T]:
        """A value read from a source, not calculated."""
        return cls(
            value=value,
            unit=unit,
            status=status,
            tier=source.tier,
            confidence=min(confidence, TIER_CEILING[source.tier]),
            source=source,
            valid_as_of=valid_as_of,
            caveats=caveats or [],
        )

    @classmethod
    def conflict(
        cls,
        candidates: list[Candidate[T]],
        *,
        reason: str,
        unit: str | None = None,
    ) -> Fact[T]:
        """Sources disagree. Show both, resolve nothing, flag it RED."""
        return cls(
            value=None,
            unit=unit,
            status=Status.CONFLICT,
            tier=Tier.T5,
            confidence=0.0,
            reason=reason,
            candidates=candidates,
        )

    # ---- derivation -----------------------------------------------------

    @classmethod
    def derive(
        cls,
        value: T,
        *,
        inputs: list[Fact[Any]],
        method: Method,
        assumptions: list[str],
        unit: str | None = None,
        status: Status = Status.COMPUTED,
        caveats: list[str] | None = None,
        rule_ids: list[str] | None = None,
    ) -> Fact[T]:
        """Build a fact from other facts.

        The rule that makes the whole confidence system trustworthy lives here:
        a derived fact can never be more confident than its weakest input.
        """
        if not assumptions and status is Status.COMPUTED:
            raise ValueError("derived COMPUTED facts must declare assumptions")

        missing = [f for f in inputs if f.status is Status.UNAVAILABLE]
        if missing:
            raise ValueError(
                "cannot derive from UNAVAILABLE inputs; the caller must return "
                "Fact.unavailable() with the blocking reason instead"
            )

        weakest = min((f.confidence for f in inputs), default=1.0)
        confidence = round(weakest * METHOD_FACTOR[method], 4)

        inherited = sorted({c for f in inputs for c in f.caveats})

        return cls(
            value=value,
            unit=unit,
            status=status,
            tier=Tier.T5,
            confidence=confidence,
            assumptions=assumptions,
            caveats=(caveats or []) + inherited,
            method=method,
            derived_from=[f.id for f in inputs],
            rule_ids=rule_ids or [],
        )

    # ---- presentation ---------------------------------------------------

    @property
    def colour(self) -> str:
        """UI status colour. Never used decoratively — status only."""
        match self.status:
            case Status.VERIFIED:
                return "GREEN"
            case Status.INDICATIVE | Status.COMPUTED | Status.ESTIMATED:
                return "AMBER"
            case Status.CONFLICT:
                return "RED"
            case Status.UNAVAILABLE:
                return "GREY"

    @property
    def is_known(self) -> bool:
        return self.status not in (Status.UNAVAILABLE, Status.CONFLICT)

    def __str__(self) -> str:
        if not self.is_known:
            return f"[{self.status}: {self.reason}]"
        unit = f" {self.unit}" if self.unit else ""
        return f"{self.value}{unit} ({self.status}, {self.confidence:.0%})"
