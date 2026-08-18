"""Source registry endpoints — the data-source audit, served live.

Because the UI reads this rather than a static document, the running system and
docs/01-data-source-audit.md cannot quietly drift apart.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.disclaimers import STANDARD_SET
from app.services import cities

router = APIRouter()

ROOT = Path(__file__).resolve().parents[4]
PROCESSED = ROOT / "data" / "processed"
ARTIFACTS = ROOT / "ml" / "artifacts"


class SourceOut(BaseModel):
    id: UUID
    name: str
    organisation: str | None
    source_url: str | None
    tier: str
    availability: str
    licence: str | None
    attribution: str | None
    retrieved_at: datetime | None
    source_updated: date | None
    max_confidence: float
    verification_status: str
    access_notes: str | None
    download_url: str | None = None
    transformation: str | None = None
    caveats: list[str] = []
    # A null licence can mean "none stated" or "we could not read it". Those are
    # different and the difference matters before redistribution.
    licence_status: str | None = None
    retrieval_path: str | None = None


class SourceListResponse(BaseModel):
    data: list[SourceOut]
    count: int = 0
    note: str = (
        "Read from the provenance sidecar each ingest writes beside its output, "
        "so this registry cannot drift from what was actually downloaded."
    )
    disclaimers: list[str] = list(STANDARD_SET)


def _sidecar(path: Path) -> SourceOut | None:
    try:
        d: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    url = d.get("source_url") or d.get("download_url") or path.stem
    return SourceOut(
        id=uuid5(NAMESPACE_URL, url),
        name=d.get("name", path.stem),
        organisation=d.get("organisation"),
        source_url=d.get("source_url"),
        download_url=d.get("download_url"),
        tier=d.get("tier", "UNKNOWN"),
        availability=d.get("availability", "UNKNOWN"),
        licence=d.get("licence"),
        attribution=d.get("attribution"),
        retrieved_at=(datetime.fromisoformat(d["retrieved_at"])
                      if d.get("retrieved_at") else None),
        source_updated=(date.fromisoformat(d["source_updated"])
                        if d.get("source_updated") else None),
        max_confidence=float(d.get("max_confidence", 0.5)),
        verification_status=d.get("verification_status", "UNVERIFIED"),
        access_notes=d.get("access_notes"),
        transformation=d.get("transformation"),
        caveats=list(d.get("caveats", [])),
        licence_status=d.get("licence_status"),
        retrieval_path=d.get("retrieval_path"),
    )


# _training_datasets() used to synthesise registry rows from metrics.json. It
# asserted a licence of "As published by the dataset host", which was a
# fabrication — nobody had read the licence. Both property datasets now have
# real provenance sidecars in data/processed/ recording their Kaggle upstream,
# the mirror actually fetched, and licence_status UNVERIFIED. The sidecar
# scanner below picks them up like any other layer.


@router.get("", response_model=SourceListResponse, summary="List registered data sources")
async def list_sources() -> SourceListResponse:
    """Every dataset the platform has ingested, with tier, licence and access notes.

    An empty list is the correct answer before any ingest has run — not an error.
    """
    found = [s for p in sorted(PROCESSED.glob("source_*.json"))
             if (s := _sidecar(p)) is not None]
    # Highest-trust first, so a T2 boundary layer never sits below a T4 dataset.
    found.sort(key=lambda s: (s.tier, s.name))
    return SourceListResponse(data=found, count=len(found))
