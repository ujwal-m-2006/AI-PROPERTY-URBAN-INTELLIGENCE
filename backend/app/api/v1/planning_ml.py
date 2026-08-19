"""Planning ML — the ablation study and ward typologies.

Serves `ml/artifacts/<city>/planning_models.json` from
`ml/pipelines/train_planning_models.py`.

The interesting content is negative. One layer made the model worse and is
reported as such; Bengaluru's ward typologies are too weakly separated to
classify a ward with, and say so. An endpoint that returned only the layers that
helped would answer "did you use all the datasets" with a yes that means nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from app.core.disclaimers import PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS
from app.core.problems import DataUnavailable
from app.services import cities

router = APIRouter()

ARTIFACTS = Path(__file__).resolve().parents[4] / "ml" / "artifacts"

NOT_A_RANKING = (
    "Ward typologies are groupings, not rankings. No dataset carries an observed "
    "'development pressure' or 'underserved' label, so none is predicted. A "
    "typology number carries no ordering — typology 0 is not worse than 2."
)


def _payload(city_id: str) -> dict[str, Any]:
    path = ARTIFACTS / city_id / "planning_models.json"
    if not path.exists():
        raise DataUnavailable(
            f"No planning models for {city_id}. Run "
            f"`python ml/pipelines/train_planning_models.py {city_id}`.",
            city=city_id,
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("", summary="Layer ablation and ward typologies")
async def planning_ml(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    d = _payload(c.id)
    ablation = d.get("ablation", [])

    return {
        "city": {"id": c.id, "name": c.name},
        "target_label": d.get("target_label"),
        "validation": d.get("validation"),
        "layers_joined": d.get("layers_joined", {}),
        "excluded_features": d.get("excluded_features", {}),
        "ablation": ablation,
        "best": d.get("best"),
        "layers_that_helped": d.get("layers_that_helped", []),
        "layers_that_did_not": d.get("layers_that_did_not", []),
        "honest_reading": d.get("honest_reading"),
        "ward_typology": d.get("ward_typology", {}),
        "not_a_ranking": NOT_A_RANKING,
        "generated_at": d.get("generated_at"),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }


@router.get("/ablation", summary="Did each dataset earn its place?")
async def ablation(city: str = Query("bengaluru")) -> dict[str, Any]:
    """The direct answer to 'are you using all the datasets'.

    Yes — and each one was measured. Adding a feature that does not improve
    out-of-locality generalisation makes the model worse while making it look
    richer, so the verdict per layer is reported rather than the final number
    alone.
    """
    c = cities.get(city)
    d = _payload(c.id)
    steps = d.get("ablation", [])

    helped = [s for s in steps if s.get("verdict") == "HELPS"]
    hurt = [s for s in steps if s.get("verdict") == "HURTS"]
    neutral = [s for s in steps if s.get("verdict") == "no effect"]

    return {
        "city": {"id": c.id, "name": c.name},
        "steps": steps,
        "summary": {
            "layers_tested": max(len(steps) - 1, 0),
            "helped": len(helped),
            "hurt": len(hurt),
            "no_effect": len(neutral),
        },
        "best_r2": (d.get("best") or {}).get("spatial_cv_r2"),
        "best_features": (d.get("best") or {}).get("features"),
        "verdict": d.get("honest_reading"),
        "why_this_matters": (
            "A feature that does not improve generalisation is noise with a "
            "plausible name. Keeping it because the dataset exists is how a "
            "model gets worse while its feature list gets longer."
        ),
        "excluded_by_name": d.get("excluded_features", {}),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }


@router.get("/typology", summary="Ward typologies, with their separation quality")
async def typology(city: str = Query("bengaluru")) -> dict[str, Any]:
    c = cities.get(city)
    t = _payload(c.id).get("ward_typology", {})

    if not t.get("available"):
        return {
            "city": {"id": c.id, "name": c.name},
            "available": False,
            "reason": t.get("reason", "Typologies not computed."),
            "not_a_finding": (
                "This is not a finding that the city's wards are uniform."
            ),
        }

    return {
        "city": {"id": c.id, "name": c.name},
        "available": True,
        "method": t.get("method"),
        "k": t.get("k"),
        "k_selection": t.get("k_selection"),
        "silhouette": t.get("silhouette"),
        "validity_by_k": t.get("validity_by_k", {}),
        "chosen_k_by_index": t.get("chosen_k_by_index", {}),
        "indices_agree_on_k": t.get("indices_agree_on_k"),
        "validity_note": t.get("validity_note"),
        "well_separated": t.get("well_separated"),
        "warning": t.get("warning"),
        # Two independent reasons to distrust these groups, and both must hold
        # before they may be used to classify a ward: the clusters must
        # actually separate, AND the three validity indices must agree on how
        # many there are. Either failure alone makes k a modelling choice.
        "usable_for_classification": bool(t.get("well_separated"))
                                     and bool(t.get("indices_agree_on_k")),
        "usable_for_classification_criteria": [
            {"criterion": "clusters actually separate (silhouette >= 0.35)",
             "met": bool(t.get("well_separated")),
             "value": t.get("silhouette")},
            {"criterion": "all three validity indices choose the same k",
             "met": bool(t.get("indices_agree_on_k")),
             "value": t.get("chosen_k_by_index", {})},
        ],
        "wards_clustered": t.get("wards_clustered"),
        "features_used": t.get("features_used", []),
        "clusters": t.get("clusters", []),
        "not_a_ranking": t.get("not_a_label", NOT_A_RANKING),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }
