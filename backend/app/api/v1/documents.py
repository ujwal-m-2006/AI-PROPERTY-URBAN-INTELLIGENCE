"""Module 27 — document intelligence endpoints.

The audit's design rule for the whole property-records block: the platform
stores what the *user* supplies, checks it against what it independently knows,
and otherwise deep-links to the official portal. This is that module.

Nothing here writes to disk or to a log. See `app/services/documents.py`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, UploadFile
from pydantic import BaseModel, Field

from app.core.disclaimers import PLATFORM_NATURE
from app.services import cities, documents, jurisdiction

router = APIRouter()

OFFICIAL_LINKS = {
    "bengaluru": [
        {"name": "e-Aasthi / e-Khata (Revenue Department)",
         "url": "https://landrecords.karnataka.gov.in",
         "for": "Khata certificate and extract, e-Khata records"},
        {"name": "Kaveri Online Services (Stamps and Registration)",
         "url": "https://kaveri.karnataka.gov.in",
         "for": "Encumbrance Certificate, registered deeds, guidance value"},
        {"name": "Bengaluru property tax portal",
         "url": "https://bbmptax.karnataka.gov.in",
         "for": "Property tax / SAS status"},
    ],
    "chennai": [
        {"name": "TNREGINET (Registration Department, Tamil Nadu)",
         "url": "https://tnreginet.gov.in",
         "for": "Encumbrance Certificate, registered deeds, guideline value"},
        {"name": "Greater Chennai Corporation property tax",
         "url": "https://chennaicorporation.gov.in",
         "for": "Property tax status"},
    ],
}


class DocumentRequest(BaseModel):
    """Document text the user supplies. Never persisted."""

    text: str = Field(..., min_length=10, max_length=200_000)
    city: str = "bengaluru"
    # Optional: cross-check against the jurisdiction at a specific point.
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)


@router.post("/analyze", summary="Analyse a property document supplied by the user")
async def analyze(req: DocumentRequest) -> dict[str, Any]:
    """Extract known fields and cross-check them against official boundary data.

    A CONSISTENT result is evidence of internal consistency, never verification
    of the document. Nothing supplied here is stored.
    """
    c = cities.get(req.city)

    known: dict[str, Any] = {}
    location_used = None
    if req.lat is not None and req.lng is not None:
        result = jurisdiction.jurisdiction(req.lng, req.lat, c.id)
        known = {
            k: {"value": f.value, "reason": f.reason, "status": str(f.status)}
            for k, f in result.facts.items()
        }
        location_used = {"lat": req.lat, "lng": req.lng, "found": result.found}

    out = documents.analyse(req.text, known)
    out["city"] = {"id": c.id, "name": c.name}
    out["location_used"] = location_used
    if location_used is None:
        out["cross_check_note"] = (
            "No location was supplied, so no field could be cross-checked "
            "against official boundary data. Supply lat and lng to compare."
        )
    out["next_steps"] = {
        "note": (
            "This platform cannot verify a government record. These are the "
            "official sources that can."
        ),
        "official_sources": OFFICIAL_LINKS.get(c.id, []),
    }
    out["disclaimers"] = [PLATFORM_NATURE, documents.NOT_VERIFICATION]
    return out


@router.post("/upload", summary="Upload a document file (text formats only)")
async def upload(file: UploadFile, city: str = "bengaluru",
                 lat: float | None = None, lng: float | None = None) -> dict[str, Any]:
    """Accept a text-bearing file. Images and PDFs are refused, with the reason.

    No OCR engine is installed in this deployment. Accepting an image and
    returning fields would mean inventing them, so the upload is refused
    instead — the same rule the rest of the platform follows.
    """
    name = (file.filename or "").lower()
    raw = await file.read()

    if name.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".pdf")):
        return {
            "analysed": False,
            "reason": (
                f"'{file.filename}' is an image or PDF, and no OCR engine is "
                "installed in this deployment. Returning extracted fields from "
                "a file the system cannot read would be fabrication."
            ),
            "what_to_do": (
                "Open the document, copy its text, and paste it into the text "
                "box — the analysis is identical once the text is available."
            ),
            "ocr_status": "NOT INSTALLED",
            "stored": False,
        }

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "analysed": False,
            "reason": "File is not UTF-8 text and could not be decoded.",
            "stored": False,
        }

    if len(text.strip()) < 10:
        return {"analysed": False, "reason": "File contains no usable text.",
                "stored": False}

    c = cities.get(city)
    known: dict[str, Any] = {}
    if lat is not None and lng is not None:
        result = jurisdiction.jurisdiction(lng, lat, c.id)
        known = {k: {"value": f.value, "reason": f.reason, "status": str(f.status)}
                 for k, f in result.facts.items()}

    out = documents.analyse(text, known)
    out["analysed"] = True
    out["city"] = {"id": c.id, "name": c.name}
    out["filename_note"] = (
        "The file was read into memory and discarded. It was not saved."
    )
    out["disclaimers"] = [PLATFORM_NATURE, documents.NOT_VERIFICATION]
    return out


@router.get("/capabilities", summary="What this module can and cannot read")
async def capabilities(city: str = "bengaluru") -> dict[str, Any]:
    c = cities.get(city)
    return {
        "city": {"id": c.id, "name": c.name},
        "accepts": ["pasted text", "UTF-8 text file"],
        "refuses": {
            "images_and_pdf": (
                "No OCR engine is installed. The module refuses rather than "
                "returning fields it did not read."
            ),
        },
        "extractable_fields": sorted(documents.PATTERNS),
        "cross_checked_against": [
            "GBA ward and corporation boundaries",
            "revenue sheets (taluk, hobli, village, survey number)",
        ],
        "retention": {"stored": False, "note": documents.NOTHING_STORED},
        "privacy": {
            "personal_data_echoed": False,
            "note": documents.PERSONAL_DATA_NOTE,
        },
        "cannot_do": [
            "Verify that a document is genuine or current",
            "Confirm ownership or title — Khata is not title",
            "Fetch any government record on your behalf",
        ],
        "official_sources": OFFICIAL_LINKS.get(c.id, []),
        "disclaimers": [PLATFORM_NATURE, documents.NOT_VERIFICATION],
    }
