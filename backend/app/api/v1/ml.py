"""ML Performance dashboard API — the graded core.

Serves exactly what `ml/pipelines/train_city_model.py` wrote. Nothing here is
computed on the fly and nothing is hard-coded: if a metric is not in the
artifact, the endpoint says so rather than inventing a number.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.core.disclaimers import PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS
from app.core.problems import DataUnavailable
from app.services import cities

router = APIRouter()

ARTIFACTS = Path(__file__).resolve().parents[4] / "ml" / "artifacts"


def _metrics(city_id: str) -> dict[str, Any]:
    path = ARTIFACTS / city_id / "metrics.json"
    if not path.exists():
        raise DataUnavailable(
            f"No trained model artifact for {city_id}. Run "
            f"`python ml/pipelines/train_city_model.py {city_id}`.",
            city=city_id,
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/summary", summary="ML lifecycle summary for a city")
async def summary(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    m = _metrics(c.id)

    comparison = m.get("model_comparison", {})
    rows = [
        {
            "algorithm": name,
            "random_cv_r2": r["random_cv"]["r2"],
            "spatial_cv_r2": r["spatial_cv"]["r2"],
            "leakage_gap_r2": r["leakage_gap_r2"],
            "mae": r["spatial_cv"]["mae"],
            "rmse": r["spatial_cv"]["rmse"],
            "mape_pct": r["spatial_cv"]["mape_pct"],
            "selected": name == m.get("algorithm"),
        }
        for name, r in comparison.items()
    ]
    rows.sort(key=lambda r: -r["spatial_cv_r2"])

    worst_leak = max(rows, key=lambda r: r["leakage_gap_r2"]) if rows else None

    return {
        "city": {"id": c.id, "name": c.name, "authority": c.authority},
        "dataset": m.get("dataset", {}),
        "target": {
            "name": m.get("target"),
            "label": m.get("target_label"),
            "note": m.get("target_note"),
        },
        "selected_model": m.get("algorithm"),
        "model_comparison": rows,
        "tuning": m.get("tuning", {}),
        "final_test_metrics": m.get("final_test_metrics", {}),
        "test_split_warning": m.get("test_split_warning"),
        "honest_generalisation_r2": m.get("honest_generalisation_r2"),
        "conformal": m.get("conformal", {}),
        "leakage_finding": (
            {
                "algorithm": worst_leak["algorithm"],
                "random_cv_r2": worst_leak["random_cv_r2"],
                "spatial_cv_r2": worst_leak["spatial_cv_r2"],
                "gap": worst_leak["leakage_gap_r2"],
                "explanation": (
                    "Random k-fold places a property and its neighbour on "
                    "opposite sides of the split, so the model can memorise a "
                    "locality's price level. Spatial-block CV groups whole "
                    "wards/localities into the same fold. The gap is the part "
                    "of the reported accuracy that was leakage."
                ),
            }
            if worst_leak else None
        ),
        "cleaning_log": m.get("cleaning_log", []),
        "gis": m.get("gis", {}),
        "trained_at": m.get("trained_at"),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }


@router.get("/eda", summary="Exploratory data analysis for a city")
async def eda(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    m = _metrics(c.id)
    e = m.get("eda", {})
    if not e:
        raise DataUnavailable(f"No EDA section in the {c.id} artifact")
    return {
        "city": {"id": c.id, "name": c.name},
        "rows": e.get("rows"),
        "columns": e.get("columns"),
        "duplicate_rows": e.get("duplicate_rows"),
        "missing_values": e.get("missing_values", {}),
        "target": e.get("target", {}),
        "target_outliers_iqr": e.get("target_outliers_iqr"),
        "correlation_with_target": e.get("correlation_with_target", {}),
        "top_localities": e.get("top_localities", {}),
        "plots": e.get("plots", []),
    }


@router.get("/explain", summary="Global explainability (SHAP + permutation)")
async def explain(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    m = _metrics(c.id)
    return {
        "city": {"id": c.id, "name": c.name},
        "algorithm": m.get("algorithm"),
        "permutation_importance": m.get("permutation_importance", []),
        "shap_importance": m.get("shap_importance", []),
        "method_note": (
            "Permutation importance is measured on the spatially-honest held-out "
            "test split, not impurity importance (which is biased toward "
            "high-cardinality features). SHAP values are mean |SHAP| over a "
            "sample of the test split."
        ),
    }


@router.get("/plot/{city}/{name:path}", summary="Serve a generated plot")
async def plot(city: str, name: str) -> FileResponse:
    c = cities.get(city)
    # Contain the path — no traversal outside the city's artifact directory.
    base = (ARTIFACTS / c.id).resolve()
    target = (base / name).resolve()
    if not str(target).startswith(str(base)) or target.suffix.lower() != ".png":
        raise DataUnavailable("Invalid plot path")
    if not target.exists():
        raise DataUnavailable(
            f"Plot {name!r} not generated for {c.id}. Re-run the training pipeline."
        )
    return FileResponse(target, media_type="image/png")


@router.get("/future-price", summary="Future price analysis (Module 15)")
async def future_price(city: str = Query("bengaluru")) -> dict[str, Any]:
    """Temporal analysis for a city.

    Returns a forecast only where the data supports one. Where it does not, it
    returns the reason and whatever temporal analysis IS supported, rather than
    an invented trend.
    """
    c = cities.get(city)
    path = ARTIFACTS / c.id / "future_price.json"
    if not path.exists():
        raise DataUnavailable(
            f"No temporal analysis for {c.name}. Run "
            f"`python ml/pipelines/train_future_price.py {c.id}`.",
            city=c.id,
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["city_name"] = c.name
    payload["disclaimers"] = [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS]
    return payload


@router.get("/compare", summary="Bengaluru vs Chennai — city-level ML comparison")
async def compare() -> dict[str, Any]:
    out = []
    for c in cities.all_cities():
        try:
            m = _metrics(c.id)
        except DataUnavailable:
            out.append({
                "city": c.name, "id": c.id, "available": False,
                "reason": "Model not yet trained for this city",
            })
            continue
        eda_t = m.get("eda", {}).get("target", {})
        out.append({
            "city": c.name,
            "id": c.id,
            "available": True,
            "authority": c.authority,
            "wards": c.ward_count,
            "target_label": m.get("target_label"),
            "target_note": m.get("target_note"),
            "median_price_per_sqft": eda_t.get("median"),
            "mean_price_per_sqft": eda_t.get("mean"),
            "rows": m.get("dataset", {}).get("rows_clean"),
            "algorithm": m.get("algorithm"),
            "spatial_cv_r2": (
                m.get("model_comparison", {})
                .get(m.get("algorithm", ""), {})
                .get("spatial_cv", {})
                .get("r2")
            ),
            "test_mae": m.get("final_test_metrics", {}).get("mae"),
            "supports_temporal": c.supports_temporal,
        })

    return {
        "data": out,
        "caveat": (
            "City-level comparison only. The two datasets measure DIFFERENT "
            "things — Bengaluru is asking price, Chennai is recorded sale price "
            "from an older period. Individual properties across the two cities "
            "are NOT directly comparable, and the models are trained separately "
            "with no pooled data."
        ),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }

@router.get("/registry", summary="Every model actually trained, read off disk")
async def registry(city: str = Query("bengaluru")) -> dict[str, Any]:
    """The model registry — what was trained, and whether it works.

    Anchored to files on disk rather than to the code's intentions, and it
    reports the models that do NOT work alongside the ones that do.
    """
    from app.services import model_registry

    c = cities.get(city)
    d = model_registry.registry(c.id)
    d["city"] = {"id": c.id, "name": c.name}
    return d
