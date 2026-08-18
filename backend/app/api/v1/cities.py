"""City registry endpoints — powers the Greater Bengaluru / Chennai switcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.services import cities as svc

router = APIRouter()

ROOT = Path(__file__).resolve().parents[4]


def _readiness(c) -> dict[str, bool]:
    """What is actually present on disk for this city, checked not assumed."""
    return {
        "wards": (ROOT / "data" / "processed" / c.wards_file).exists(),
        "amenities": (ROOT / "data" / "processed" / c.amenities_file).exists(),
        "dataset": (ROOT / "data" / "raw" / c.dataset_file).exists(),
        "model": (ROOT / "models" / c.model_dir / "price_model.joblib").exists(),
        "metrics": (ROOT / "ml" / "artifacts" / c.id / "metrics.json").exists(),
    }


@router.get("", summary="Available cities")
async def list_cities() -> dict[str, Any]:
    out = []
    for c in svc.all_cities():
        ready = _readiness(c)
        out.append({
            "id": c.id,
            "name": c.name,
            "name_local": c.name_local,
            "authority": c.authority,
            "authority_short": c.authority_short,
            "ward_count": c.ward_count,
            "subdivision_label": c.subdivision_label,
            "centre": {"lng": c.centre[0], "lat": c.centre[1]},
            "bbox": list(c.bbox),
            "price_target": c.price_target,
            "price_target_note": c.price_target_note,
            "supports_temporal": c.supports_temporal,
            "notes": c.notes,
            "primary": c.id == svc.DEFAULT_CITY,
            "readiness": ready,
            "ready": all(ready.values()),
        })
    return {
        "default": svc.DEFAULT_CITY,
        "data": out,
        "note": (
            "Bengaluru is the primary city. Datasets, pipelines and models are "
            "kept entirely separate per city — property prices are never pooled "
            "across cities for training or comparison."
        ),
    }


@router.get("/{city_id}", summary="City detail")
async def city_detail(city_id: str) -> dict[str, Any]:
    c = svc.get(city_id)
    ready = _readiness(c)
    return {
        "id": c.id,
        "name": c.name,
        "name_local": c.name_local,
        "authority": c.authority,
        "ward_count": c.ward_count,
        "subdivision_label": c.subdivision_label,
        "centre": {"lng": c.centre[0], "lat": c.centre[1]},
        "price_target": c.price_target,
        "price_target_note": c.price_target_note,
        "supports_temporal": c.supports_temporal,
        "notes": c.notes,
        "readiness": ready,
        "ready": all(ready.values()),
    }
