"""What-if scenario endpoints.

Re-runs the trained price model with one input changed. Read
`app/services/whatif.py` before extending: the two guards there — extrapolation
and insensitivity — are what separate this from a number generator.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.core.disclaimers import PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS
from app.services import cities, valuation, whatif

router = APIRouter()


def _predict(city: str, spec: dict[str, Any]) -> float | None:
    """Price per sq.ft for one property spec, or None if the model is absent."""
    try:
        facts = valuation.estimate(
            valuation.ValuationInput(
                sqft=float(spec.get("sqft") or 1200),
                rooms=int(spec.get("rooms") or 2),
                bath=spec.get("bath"),
                balcony=spec.get("balcony"),
                corporation=spec.get("corporation"),
                ready_to_move=bool(spec.get("ready_to_move", True)),
            ),
            city=city,
        )
    except Exception:                                   # noqa: BLE001
        return None
    fact = facts.get("price_per_sqft")
    return float(fact.value) if fact is not None and fact.is_known else None


class ScenarioRequest(BaseModel):
    city: str = "bengaluru"
    sqft: float = Field(1200, gt=100, le=100_000)
    rooms: int = Field(2, ge=1, le=20)
    bath: float | None = Field(None, ge=0, le=20)
    balcony: float | None = Field(None, ge=0, le=10)
    corporation: str | None = None
    # The scenario: any of the adjustable fields, changed.
    change_sqft: float | None = Field(None, gt=100, le=100_000)
    change_rooms: int | None = Field(None, ge=1, le=20)
    change_bath: float | None = Field(None, ge=0, le=20)
    change_balcony: float | None = Field(None, ge=0, le=10)


@router.post("", summary="Re-run the model with one thing changed")
async def scenario(req: ScenarioRequest) -> dict[str, Any]:
    c = cities.get(req.city)
    base = {"sqft": req.sqft, "rooms": req.rooms, "bath": req.bath,
            "balcony": req.balcony, "corporation": req.corporation}
    changes = {"sqft": req.change_sqft, "rooms": req.change_rooms,
               "bath": req.change_bath, "balcony": req.change_balcony}

    out = whatif.run(city=c.id, base=base, changes=changes, predict=_predict)
    out["city"] = {"id": c.id, "name": c.name}
    out["disclaimers"] = [PLATFORM_NATURE, PREDICTIONS_ARE_NOT_FACTS,
                          whatif.NOT_CAUSAL]
    return out


@router.get("/sweep", summary="Vary one field across a range")
async def sweep(
    field: str = Query("sqft", pattern="^(sqft|rooms|bath|balcony)$"),
    city: str = Query("bengaluru"),
    sqft: float = Query(1200, gt=100, le=100_000),
    rooms: int = Query(2, ge=1, le=20),
    bath: float | None = Query(None, ge=0, le=20),
) -> dict[str, Any]:
    """A curve rather than a single before/after.

    Shows whether the model's response to a feature is smooth, flat or stepped —
    which a single comparison cannot reveal.
    """
    c = cities.get(city)
    base = {"sqft": sqft, "rooms": rooms, "bath": bath}

    grids: dict[str, list[float]] = {
        "sqft": [400, 700, 1000, 1300, 1600, 2000, 2500, 3200, 4000, 6000],
        "rooms": [1, 2, 3, 4, 5, 6, 8],
        "bath": [1, 2, 3, 4, 5, 6],
        "balcony": [0, 1, 2, 3, 4],
    }
    out = whatif.sweep(city=c.id, base=base, field=field,
                       values=grids[field], predict=_predict)
    out["city"] = {"id": c.id, "name": c.name}
    out["disclaimers"] = [PLATFORM_NATURE, whatif.NOT_CAUSAL]
    return out
