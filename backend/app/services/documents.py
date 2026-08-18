"""Module 27 — document intelligence.

The Phase 0 audit established that no property-level government record can be
fetched programmatically. So this module is the other half of that design: the
user supplies the document, and the platform checks it for internal consistency
against everything it independently knows.

FOUR RULES THIS MODULE MUST NOT BREAK
-------------------------------------
1. **Nothing is stored.** The text is parsed in memory and discarded with the
   request. There is no database write, no file write, no log of the content.
   A property document identifies a real person; the safest store is none.

2. **Personal data is detected and NOT echoed back.** Owner names and
   Aadhaar-shaped numbers are flagged as present and then dropped. The platform
   reports *that* the document carries personal data, never *what* it says.

3. **A match is consistency, not verification.** If the ward on the document
   agrees with the ward the GBA layer returns for that point, that is evidence
   the document is internally consistent with official boundaries. It is not
   evidence that the document is genuine, current, or that the person holds
   title. Only the Sub-Registrar and the issuing authority can say that.

4. **Extraction is INDICATIVE.** Pattern-matching text is not reading. A field
   this module fails to find is reported as not found, never as absent from the
   document.

OCR is deliberately not implemented here — no OCR engine is installed, and
claiming to read an image the system cannot read would be the exact failure this
project is built against. Text is accepted; images are refused with the reason.
"""

from __future__ import annotations

import re
from typing import Any

# --- what a document is checked against ---------------------------------

MATCH = "CONSISTENT"
MISMATCH = "INCONSISTENT"
UNVERIFIABLE = "NOT VERIFIABLE"
NOT_FOUND = "NOT FOUND IN DOCUMENT"

NOT_VERIFICATION = (
    "A CONSISTENT result means the document agrees with official boundary data "
    "for this location. It is NOT verification that the document is genuine, "
    "current, or that the holder has title. Khata is not title. Only the "
    "Sub-Registrar and the issuing authority can confirm those."
)

NOTHING_STORED = (
    "This document was parsed in memory and discarded. No part of it was "
    "written to disk, logged, or retained after this response."
)

PERSONAL_DATA_NOTE = (
    "Personal data was detected in this document and has NOT been echoed back. "
    "The platform reports that it is present, never its content."
)

# --- extraction patterns ------------------------------------------------
# Deliberately conservative. A pattern that fires on the wrong thing produces a
# confident wrong field, which is worse than finding nothing.

PATTERNS: dict[str, re.Pattern[str]] = {
    "khata_number": re.compile(
        r"(?:khata|khatha)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,24})",
        re.I),
    "pid": re.compile(
        r"\bPID\s*(?:no\.?|number)?\s*[:\-]?\s*([0-9]{1,4}[\-/][0-9]{1,4}[\-/][0-9]{1,6})",
        re.I),
    "epid": re.compile(
        r"\bE[\-\s]?PID\s*(?:no\.?|number)?\s*[:\-]?\s*([A-Z0-9\-/]{4,24})", re.I),
    "survey_number": re.compile(
        r"(?:survey|sy\.?)\s*(?:no\.?|number)\s*[:\-]?\s*([0-9]{1,4}(?:\s*/\s*[0-9A-Z]{1,4})?)",
        re.I),
    "ward_number": re.compile(
        r"ward\s*(?:no\.?|number)\s*[:\-]?\s*([0-9]{1,3})", re.I),
    "ward_name": re.compile(
        r"ward\s*name\s*[:\-]?\s*([A-Za-z][A-Za-z .'\-]{2,40})", re.I),
    "municipal_number": re.compile(
        r"(?:municipal|property)\s*(?:no\.?|number)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,24})",
        re.I),
    "extent_sqft": re.compile(
        r"(?:extent|plot\s*area|site\s*area)\s*[:\-]?\s*([0-9,]{2,9})\s*(?:sq\.?\s*ft|sft)",
        re.I),
    "taluk": re.compile(r"taluk\s*[:\-]?\s*([A-Za-z][A-Za-z ()\-]{2,30})", re.I),
    "hobli": re.compile(r"hobli\s*[:\-]?\s*([A-Za-z][A-Za-z ()\-]{2,30})", re.I),
    "village": re.compile(r"village\s*[:\-]?\s*([A-Za-z][A-Za-z ()\-]{2,30})", re.I),
}

# Presence detectors only — these values are never returned.
PERSONAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "owner_name": re.compile(r"(?:owner|khatedar|name)\s*[:\-]\s*[A-Z][a-z]+\s+[A-Z]", re.I),
    "aadhaar_like": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "phone_like": re.compile(r"\b(?:\+91[\-\s]?)?[6-9]\d{9}\b"),
}

DOCUMENT_HINTS: dict[str, tuple[str, ...]] = {
    "Khata certificate": ("khata certificate", "khatha certificate"),
    "Khata extract": ("khata extract", "khatha extract"),
    "e-Khata / e-Aasthi record": ("e-khata", "e-aasthi", "eaasthi"),
    "Property tax receipt / SAS": ("property tax", "sas application", "tax paid"),
    "Encumbrance Certificate": ("encumbrance",),
    "Sale deed": ("sale deed", "deed of sale"),
    "Sanctioned plan / OC": ("occupancy certificate", "commencement certificate",
                             "sanctioned plan"),
}


def _clean(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip(" .:-")


def detect_document_type(text: str) -> dict[str, Any]:
    low = text.lower()
    hits = [name for name, keys in DOCUMENT_HINTS.items()
            if any(k in low for k in keys)]
    return {
        "detected": hits,
        "method": "keyword match — INDICATIVE",
        "caveat": (
            "Document type is guessed from keywords in the text. It is not a "
            "validation that the document is of that type or is authentic."
        ),
    }


def extract(text: str) -> dict[str, Any]:
    """Pull known fields out of document text. Never invents a field."""
    found: dict[str, str] = {}
    for key, pattern in PATTERNS.items():
        m = pattern.search(text)
        if m:
            found[key] = _clean(m.group(1))
    return found


def detect_personal_data(text: str) -> list[str]:
    """Report which kinds of personal data are present. Never the values."""
    return [name for name, pattern in PERSONAL_PATTERNS.items()
            if pattern.search(text)]


def _norm(v: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v).lower())


def cross_check(extracted: dict[str, str],
                known: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare document fields against independently-established facts.

    `known` is the jurisdiction answer for the same location — facts this
    platform derived from official boundary data without seeing the document.
    """
    checks: list[dict[str, Any]] = []

    comparisons = [
        ("ward_number", "ward_no", "Ward number"),
        ("ward_name", "ward_name", "Ward name"),
        ("taluk", "taluk", "Taluk"),
        ("hobli", "hobli", "Hobli"),
        ("village", "village", "Village"),
        ("survey_number", "survey_number", "Survey number"),
    ]

    for doc_key, fact_key, label in comparisons:
        doc_value = extracted.get(doc_key)
        fact = known.get(fact_key) or {}
        fact_value = fact.get("value")

        if doc_value is None:
            checks.append({
                "field": label, "verdict": NOT_FOUND, "document": None,
                "platform": fact_value,
                "note": ("This field was not found in the text. That is not "
                         "evidence it is absent from the document."),
            })
            continue

        if fact_value in (None, ""):
            checks.append({
                "field": label, "verdict": UNVERIFIABLE, "document": doc_value,
                "platform": None,
                "note": (fact.get("reason")
                         or "The platform holds no independent value to compare."),
            })
            continue

        a, b = _norm(doc_value), _norm(fact_value)
        agrees = a == b or (len(a) >= 3 and (a in b or b in a))
        checks.append({
            "field": label,
            "verdict": MATCH if agrees else MISMATCH,
            "document": doc_value,
            "platform": fact_value,
            "note": (
                "Document agrees with official boundary data for this location."
                if agrees else
                "Document disagrees with official boundary data for this "
                "location. This may mean the document is for a different "
                "property, predates a boundary change, or was transcribed "
                "differently — it is a prompt to check, not a finding of fraud."
            ),
        })

    return checks


def summarise(checks: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {MATCH: 0, MISMATCH: 0, UNVERIFIABLE: 0, NOT_FOUND: 0}
    for c in checks:
        counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1

    if counts[MISMATCH]:
        headline = "INCONSISTENCIES FOUND — verify before relying on this document"
    elif counts[MATCH]:
        headline = (f"{counts[MATCH]} field(s) consistent with official boundary "
                    "data. This is not verification of the document.")
    else:
        headline = ("Nothing could be cross-checked. No comparable field was "
                    "found in the text, or the platform holds no independent "
                    "value for this location.")

    return {
        "headline": headline,
        "counts": counts,
        "verified": False,          # never true — see NOT_VERIFICATION
        "why_never_verified": NOT_VERIFICATION,
    }


def analyse(text: str, known: dict[str, Any] | None = None) -> dict[str, Any]:
    """Full analysis of a pasted document. Stores nothing."""
    known = known or {}
    personal = detect_personal_data(text)
    extracted = extract(text)
    checks = cross_check(extracted, known)

    return {
        "document_type": detect_document_type(text),
        "extracted_fields": extracted,
        "extraction_method": "regular-expression extraction — INDICATIVE",
        "fields_found": len(extracted),
        "cross_check": checks,
        "summary": summarise(checks),
        "personal_data": {
            "present": bool(personal),
            "kinds_detected": personal,
            "note": PERSONAL_DATA_NOTE if personal else
                    "No personal data pattern was detected. Absence of a "
                    "detection is not a guarantee that none is present.",
        },
        "retention": {"stored": False, "note": NOTHING_STORED},
    }
