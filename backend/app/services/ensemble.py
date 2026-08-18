"""Single-model, dual-model and multi-model prediction.

Three prediction strategies over the models saved by
``ml/pipelines/train_city_model.py``. Every algorithm is fitted on the same
training split with the same preprocessing, so the three modes differ only in
how many fitted models are consulted.

    SINGLE  one model — the best performer on spatial-block CV.
            Fastest, and the most interpretable: one prediction, one SHAP
            explanation, one interval.

    DUAL    the two best models, averaged. The gap between them is reported as
            model disagreement — a second, independent uncertainty signal that a
            single model cannot give you.

    MULTI   every saved model, averaged (an unweighted ensemble). Averaging
            reduces variance: individual model errors partially cancel, so the
            ensemble is usually steadier than its members, though not
            necessarily better than the single best.

Averaging is unweighted on purpose. Weighting by validation score would need a
further held-out split to choose the weights honestly, and with the data
available that split would be too small to trust.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "models"
ARTIFACTS = ROOT / "ml" / "artifacts"

Mode = Literal["single", "dual", "multi"]

MODE_INFO: dict[str, dict[str, str]] = {
    "single": {
        "label": "Single model",
        "description": (
            "One algorithm — the best performer on spatial-block "
            "cross-validation — produces the prediction."
        ),
        "why": "Fastest and most interpretable; SHAP maps to exactly one model.",
    },
    "dual": {
        "label": "Dual model",
        "description": (
            "The two best algorithms each predict, and the results are averaged."
        ),
        "why": (
            "The difference between the two is reported as model disagreement, "
            "an uncertainty signal a single model cannot provide."
        ),
    },
    "multi": {
        "label": "Multi model (ensemble)",
        "description": (
            "Every trained algorithm predicts, and the predictions are averaged."
        ),
        "why": (
            "Averaging cancels part of each model's independent error, which "
            "usually reduces variance across unseen data."
        ),
    },
}


@lru_cache(maxsize=8)
def _read_metrics(path_str: str, mtime: float) -> dict[str, Any]:
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def _catalogue(city: str) -> dict[str, Any]:
    """Saved models for a city, ranked by spatial-block CV (the honest score).

    Cached on mtime so a retrain is picked up without restarting the API.
    """
    path = ARTIFACTS / city / "metrics.json"
    if not path.exists():
        return {}
    m = _read_metrics(str(path), path.stat().st_mtime)
    saved = m.get("saved_models", {})
    ranked = sorted(
        saved.items(), key=lambda kv: -(kv[1].get("spatial_cv_r2") or -99)
    )
    return {
        "ranked": [name for name, _ in ranked],
        "detail": saved,
        "selected": m.get("algorithm"),
        "target_label": m.get("target_label"),
    }


@lru_cache(maxsize=32)
def _load_model(path_str: str, mtime: float) -> dict[str, Any]:
    import joblib

    return joblib.load(path_str)


def _load(city: str, name: str) -> dict[str, Any] | None:
    path = MODELS / city / f"model_{name}.joblib"
    if not path.exists():
        return None
    return _load_model(str(path), path.stat().st_mtime)


def available(city: str) -> list[str]:
    return _catalogue(city).get("ranked", [])


def models_for(city: str, mode: Mode) -> list[str]:
    ranked = available(city)
    if not ranked:
        return []
    if mode == "single":
        return ranked[:1]
    if mode == "dual":
        return ranked[:2]
    return ranked


def predict(
    city: str, feature_row, mode: Mode = "single"
) -> dict[str, Any]:
    """Run the requested strategy and report every contributing model."""
    names = models_for(city, mode)
    if not names:
        return {
            "available": False,
            "reason": (
                f"No saved models for {city}. Run "
                f"`python ml/pipelines/train_city_model.py {city}`."
            ),
        }

    cat = _catalogue(city)
    members: list[dict[str, Any]] = []
    values: list[float] = []
    halves: list[float] = []

    for name in names:
        bundle = _load(city, name)
        if bundle is None:
            continue
        value = float(bundle["pipeline"].predict(feature_row)[0])
        half = float(bundle.get("conformal_q") or 0.0)
        detail = cat["detail"].get(name, {})
        members.append({
            "algorithm": name,
            "prediction": round(value, 0),
            "interval_half_width": round(half, 0),
            "spatial_cv_r2": detail.get("spatial_cv_r2"),
            "test_r2": (detail.get("test_metrics") or {}).get("r2"),
            "test_mae": (detail.get("test_metrics") or {}).get("mae"),
        })
        values.append(value)
        halves.append(half)

    if not values:
        return {"available": False, "reason": "Saved model files could not be loaded."}

    point = sum(values) / len(values)
    # The ensemble interval is the mean of the members' conformal widths. Each
    # was calibrated on the same held-out split, so they are on one scale.
    half = sum(halves) / len(halves)

    spread = (max(values) - min(values)) if len(values) > 1 else 0.0
    disagreement_pct = (spread / point * 100.0) if point else 0.0

    return {
        "available": True,
        "mode": mode,
        "mode_label": MODE_INFO[mode]["label"],
        "mode_description": MODE_INFO[mode]["description"],
        "mode_rationale": MODE_INFO[mode]["why"],
        "models_used": [m["algorithm"] for m in members],
        "model_count": len(members),
        "prediction": round(point, 0),
        "range_low": round(max(point - half, 0.0), 0),
        "range_high": round(point + half, 0),
        "interval_half_width": round(half, 0),
        "members": members,
        "disagreement": {
            "spread": round(spread, 0),
            "spread_pct": round(disagreement_pct, 1),
            "note": (
                "Range between the highest and lowest member prediction. A wide "
                "spread means the algorithms disagree about this property, which "
                "is itself a reason for caution."
                if len(values) > 1
                else "Not applicable — a single model cannot disagree with itself."
            ),
        },
        "aggregation": (
            "unweighted mean of member predictions"
            if len(values) > 1 else "single model output"
        ),
        "target_label": cat.get("target_label"),
    }


def compare_modes(city: str, feature_row) -> dict[str, Any]:
    """Run all three strategies on the same input, for side-by-side comparison."""
    out = {}
    for mode in ("single", "dual", "multi"):
        out[mode] = predict(city, feature_row, mode)  # type: ignore[arg-type]
    return {
        "city": city,
        "modes": out,
        "note": (
            "All three strategies use the same fitted models and the same "
            "preprocessing pipeline; they differ only in how many models are "
            "consulted and how their outputs are combined."
        ),
    }
