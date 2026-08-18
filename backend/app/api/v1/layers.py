"""Map layer endpoints — Module 22.

Serves GeoJSON directly in the MVP. The production path is Martin serving MVT
from PostGIS (docker-compose profile `phase3`); this keeps the demo runnable
without a database.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.problems import DataUnavailable

router = APIRouter()

# app/api/v1/layers.py -> v1, api, app, backend, <project root>
DATA = Path(__file__).resolve().parents[4] / "data" / "processed"

LAYERS: dict[str, dict[str, Any]] = {
    "wards": {
        "file": "gba_wards.geojson",
        "title": "GBA Wards (369)",
        "tier": "T2",
        "rendering": "authoritative",
        "source": "Greater Bengaluru Authority, via OpenCity",
        "source_url": "https://data.opencity.in/dataset/gba-wards-delimitation-2025",
        "licence": "Other (Public Domain) as stated by the portal",
        "valid_as_of": "2025-11-19",
    },
    "corporations": {
        "file": "gba_corporations.geojson",
        "title": "City Corporations (5)",
        "tier": "T5",
        "rendering": "derived",
        "source": "Derived by grouping ward polygons",
        "source_url": None,
        "licence": "Derived from the ward layer",
        "valid_as_of": "2025-11-19",
        "derivation_note": "Union of member ward polygons; internal edges not cleaned",
    },
    # --- Chennai ---
    "chennai_wards": {
        "file": "chennai_wards.geojson",
        "title": "GCC Wards (200)",
        "tier": "T2",
        "rendering": "authoritative",
        "source": "Greater Chennai Corporation, via OpenCity",
        "source_url": "https://data.opencity.in/dataset/gcc-ward-information",
        "licence": "As published by the OpenCity urban data portal",
        "valid_as_of": "2022-01-01",
        "city": "chennai",
    },
    "chennai_zones": {
        "file": "chennai_zones.geojson",
        "title": "GCC Zones (15)",
        "tier": "T2",
        "rendering": "authoritative",
        "source": "Greater Chennai Corporation, via OpenCity",
        "source_url": "https://data.opencity.in/dataset/gcc-ward-information",
        "licence": "As published by the OpenCity urban data portal",
        "valid_as_of": "2022-01-01",
        "city": "chennai",
    },
}


@lru_cache(maxsize=4)
def _load(name: str) -> str:
    path = DATA / LAYERS[name]["file"]
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


@router.get("/layers", summary="Layer catalogue")
async def layer_catalogue() -> dict[str, Any]:
    """Every layer with its tier, licence and rendering class.

    `rendering` drives the map style: 'derived' layers render hatched so a user
    can never mistake something we computed for something that was notified.
    """
    return {
        "data": [
            {"id": key, **{k: v for k, v in meta.items() if k != "file"}}
            for key, meta in LAYERS.items()
        ]
    }


@router.get("/layers/{name}", summary="Layer GeoJSON")
async def layer_geojson(name: str) -> JSONResponse:
    if name not in LAYERS:
        raise DataUnavailable(f"No layer named {name!r}", available=list(LAYERS))
    try:
        payload = _load(name)
    except FileNotFoundError:
        raise DataUnavailable(
            f"Layer {name!r} is registered but not yet ingested. "
            "Run etl/flows/ingest_gba_wards.py."
        ) from None

    return JSONResponse(
        content=json.loads(payload),
        headers={"Cache-Control": "public, max-age=3600"},
    )
