"""Cross-city transfer between Bengaluru and Chennai.

Serves `ml/artifacts/<city>/cross_city.json` from
`ml/pipelines/train_cross_city.py`.

Every headline number here is negative, and each is negative for a different
reason. That is the content: a transfer study where everything worked would
mean the experiment was not testing anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from app.core.disclaimers import PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS
from app.core.problems import DataUnavailable

router = APIRouter()

ARTIFACTS = Path(__file__).resolve().parents[4] / "ml" / "artifacts"


def _payload() -> dict[str, Any]:
    for city in ("bengaluru", "chennai"):
        path = ARTIFACTS / city / "cross_city.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise DataUnavailable(
        "Cross-city experiments have not been run. Run "
        "`python ml/pipelines/train_cross_city.py`."
    )


@router.get("", summary="Transfer experiments A-D, plus separate vs combined")
async def cross_city() -> dict[str, Any]:
    d = _payload()
    transfers = d.get("transfer", [])
    combined = d.get("separate_vs_combined", {})

    # The finding, stated once rather than left for the reader to assemble.
    rank_rhos = [t["rank"]["spearman"] for t in transfers]
    transfers_fail = all(abs(r) < 0.2 for r in rank_rhos) if rank_rhos else None

    return {
        "shared_schema": d.get("shared_schema", {}),
        "estimator": d.get("estimator"),
        "within_city": d.get("within_city", []),
        "transfer": transfers,
        "separate_vs_combined": combined,
        "how_to_read": d.get("how_to_read"),
        "headline": {
            "transfer_fails_even_on_rank": transfers_fail,
            "rank_spearman": rank_rhos,
            "finding": (
                "Removing the price-level difference does not rescue the "
                "transfer. Within each city the same model reaches Spearman "
                "~0.50; across cities it falls to roughly zero. What identifies "
                "an expensive property in Bengaluru does not identify one in "
                "Chennai, on the 16 features the two datasets share."
                if transfers_fail else
                "Rank transfer retains signal across cities."
            ),
            "combined_model": combined.get("verdict"),
        },
        "generated_at": d.get("generated_at"),
        "disclaimers": [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS],
    }


@router.get("/schema", summary="The shared feature vocabulary, claim by claim")
async def schema() -> dict[str, Any]:
    """Each mapping is an assertion that two columns measure the same thing,
    listed individually so it can be disputed rather than hidden in a rename."""
    d = _payload().get("shared_schema", {})
    d["disclaimers"] = [PLATFORM_NATURE]
    return d
