"""The instruments that actually govern development control here.

Located by the Phase 0.5 research pass (audit tasks R2, R3, R4, 2026-08-12).
Before that pass the feasibility module could only say that no verified source
existed. It can now name and link the governing documents — while still
refusing to publish a FAR, because naming an instrument is not the same as
transcribing its clauses.

That distinction is the whole point of this module. Citing a document the
project has not encoded is honest. Quoting numbers from a document it has not
read would not be.
"""

from __future__ import annotations

from typing import Any

# R4: RMP-2031 was given provisional approval in 2017, withdrawn around 2020,
# and the Karnataka High Court has directed the State not to approve it without
# the court's permission. RMP-2015 therefore remains operative.
OPERATIVE_PLAN = "Revised Master Plan 2015 (RMP-2015)"

ZONING_AMENDMENT: dict[str, Any] = {
    "title": "Zonal Regulations to RMP-2015 — final notification",
    "reference": "UDD 235 MNJ 2025",
    "notified_on": "2026-01-05",
    "draft_published": "2025-11",
    "issuing_authority": "Urban Development Department / Greater Bengaluru Authority",
    "source_url": "https://data.opencity.in/dataset/greater-bengaluru-amendment-regulations-2025",
    "tier": "T2",
    "licence": "Other (Public Domain)",
    "status": "LOCATED — NOT TRANSCRIBED",
    "audit_task": "R2 (closed 2026-08-12)",
}

# R3: the answer that changed a design. Bye-laws are per corporation, not
# city-wide, so any rule that fires must say which corporation's bye-laws it
# applied. Module 1 already resolves corporation as a VERIFIED fact.
CORPORATION_BYELAWS: dict[str, Any] = {
    "title": "Bengaluru City Corporation Building (Amendment) Bye-laws 2026",
    "effective_from": "2026-05-14",
    "issuing_authority": "Greater Bengaluru Authority",
    "instrument_count": 5,
    "per_corporation": True,
    "corporations": ["Central", "East", "North", "South", "West"],
    "source_url": "https://data.opencity.in/dataset/bengaluru-city-corporations-bye-laws-2026",
    "tier": "T2",
    "licence": "Other (Public Domain)",
    "status": "LOCATED — NOT TRANSCRIBED",
    "audit_task": "R3 (closed 2026-08-12)",
}

WITHDRAWN_PLAN: dict[str, Any] = {
    "title": "Revised Master Plan 2031 (RMP-2031)",
    "status": "NOT NOTIFIED — provisional approval withdrawn c. 2020",
    "why_not_used": (
        "Provisional approval was withdrawn and the Karnataka High Court has "
        "directed the State not to approve it without the court's permission. "
        "It is not the operative instrument and is not used by this engine."
    ),
    "audit_task": "R4 (closed 2026-08-12)",
}

WHY_STILL_UNAVAILABLE = (
    "The governing instruments are now identified and linked, but their clauses "
    "have not been transcribed into the rules engine. A FAR, height or setback "
    "figure published from a document this project has located but not read "
    "would be a guess wearing a citation. The engine names its sources and "
    "still declines to fire."
)

CORPORATION_NOTE = (
    "Building bye-laws are issued per city corporation, not for Bengaluru as a "
    "whole. Any figure this engine eventually publishes must state which "
    "corporation's bye-laws produced it."
)


def governing_instruments(corporation: str | None = None) -> dict[str, Any]:
    """What governs this plot, and what has and has not been encoded."""
    out: dict[str, Any] = {
        "operative_plan": OPERATIVE_PLAN,
        "zoning_amendment": ZONING_AMENDMENT,
        "corporation_byelaws": CORPORATION_BYELAWS,
        "not_used": WITHDRAWN_PLAN,
        "transcription_status": "NOT TRANSCRIBED",
        "why_values_are_still_unavailable": WHY_STILL_UNAVAILABLE,
        "corporation_note": CORPORATION_NOTE,
    }
    if corporation:
        out["applicable_byelaws"] = (
            f"Bengaluru {corporation} City Corporation Building (Amendment) "
            "Bye-laws 2026"
        )
    return out
