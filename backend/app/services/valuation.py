"""Phase 9 — price estimation service (Modules 14 & 34).

Returns a BAND, never a point. The model predicts asking price per square foot
from a public listing dataset; it is not a valuation and not a transaction
price. Every output is Status.ESTIMATED and carries that caveat.
"""

from __future__ import annotations

import json
from datetime import date
import pathlib
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

from app.facts import Category, Fact, Method, SourceRef, Status, Tier, build_report

ARTIFACTS = Path(__file__).resolve().parents[3] / "ml" / "artifacts"

DATASET_URL = (
    "https://raw.githubusercontent.com/dphi-official/Datasets/master/"
    "Bengaluru_House_Data.csv"
)

# Ceiling on any price fact. A listing dataset of uncertain vintage cannot
# support more, whatever the model's validation score says.
MAX_MARKET_CONFIDENCE = 0.45


class ValuationInput(NamedTuple):
    sqft: float
    rooms: int
    bath: float | None = None
    balcony: float | None = None
    area_type: str = "Super built-up  Area"
    corporation: str | None = None
    ready_to_move: bool = True
    # Guidance value and transaction price are keyed by locality, not
    # corporation, so the caller may supply one.
    locality: str | None = None


MODELS = Path(__file__).resolve().parents[3] / "models"


@lru_cache(maxsize=8)
def _load_bundle(path_str: str, mtime: float) -> dict[str, Any]:
    import joblib

    return joblib.load(path_str)


def _bundle(city: str = "bengaluru") -> dict[str, Any] | None:
    """Per-city model, falling back to the original single-city artifact.

    Cached on the model file's mtime, not on the city name: retraining while
    the API is running must not keep serving the previous model.
    """
    per_city = MODELS / city / "price_model.joblib"
    if per_city.exists():
        return _load_bundle(str(per_city), per_city.stat().st_mtime)

    if city == "bengaluru":
        legacy = ARTIFACTS / "price_model.joblib"
        if legacy.exists():
            return _load_bundle(str(legacy), legacy.stat().st_mtime)
    return None


@lru_cache(maxsize=8)
def _load_metrics(path_str: str, mtime: float) -> dict[str, Any]:
    return json.loads(pathlib.Path(path_str).read_text(encoding="utf-8"))


def _metrics(city: str = "bengaluru") -> dict[str, Any]:
    per_city = ARTIFACTS / city / "metrics.json"
    if per_city.exists():
        return _load_metrics(str(per_city), per_city.stat().st_mtime)
    if city == "bengaluru":
        legacy = ARTIFACTS / "metrics.json"
        if legacy.exists():
            return _load_metrics(str(legacy), legacy.stat().st_mtime)
    return {}


@lru_cache(maxsize=1)
def _source() -> SourceRef:
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, DATASET_URL),
        name="Bengaluru house listings (public dataset, asking prices)",
        organisation="Publicly mirrored dataset; original provenance unconfirmed",
        source_url=DATASET_URL,
        tier=Tier.T4,
        source_updated=date(2018, 1, 1),  # best estimate; see model card
        licence="Unconfirmed — see docs/model-cards/price-model.md",
    )


def _feature_row(inp: ValuationInput, bundle: dict[str, Any], city: str) -> pd.DataFrame:
    """Build a single-row frame matching whatever features the model expects.

    Newer per-city models were trained with GIS features; the legacy Bengaluru
    model was not. Missing columns are left as NaN for the pipeline's imputer
    rather than being invented.
    """
    features = bundle.get("features", {})
    wanted = list(features.get("numeric", [])) + list(features.get("categorical", []))

    base: dict[str, Any] = {
        # Bengaluru schema
        "sqft": inp.sqft,
        "rooms": inp.rooms,
        "bath": inp.bath if inp.bath is not None else inp.rooms,
        "balcony": inp.balcony,
        "ready_to_move": int(inp.ready_to_move),
        "area_type": inp.area_type,
        "gba_corporation": inp.corporation,
        "gis_corporation": inp.corporation,
        "area_per_room": inp.sqft / inp.rooms if inp.rooms else None,
        "bath_per_room": (
            (inp.bath / inp.rooms) if (inp.bath and inp.rooms) else None
        ),
        # Chennai schema
        "INT_SQFT": inp.sqft,
        "N_ROOM": inp.rooms,
        "N_BEDROOM": inp.rooms,
        "N_BATHROOM": inp.bath if inp.bath is not None else 1,
        "bath_per_bedroom": (
            (inp.bath / inp.rooms) if (inp.bath and inp.rooms) else None
        ),
        "has_gis": 0,
    }
    row = {c: base.get(c) for c in wanted} if wanted else base
    return pd.DataFrame([row])


def estimate(
    inp: ValuationInput, city: str = "bengaluru"
) -> dict[str, Fact[Any]]:
    facts: dict[str, Fact[Any]] = {}
    bundle = _bundle(city)

    if bundle is None:
        reason = (
            f"Price model not trained for {city}. Run "
            f"`python ml/pipelines/train_city_model.py {city}`."
        )
        for key in ("price_per_sqft", "price_range_low", "price_range_high",
                    "estimated_value", "guidance_value", "transaction_price"):
            facts[key] = Fact.unavailable(reason)
        return facts

    row = _feature_row(inp, bundle, city)
    point = float(bundle["pipeline"].predict(row)[0])
    q = float(bundle["conformal_q"])
    low, high = max(point - q, 0.0), point + q

    metrics = _metrics(city)
    algo = metrics.get("algorithm") or metrics.get("model", "")
    shipped = (
        metrics.get("model_comparison", {}).get(algo)
        or metrics.get("results_by_feature_set", {})
        .get("without_locality", {})
        .get(algo, {})
    )
    spatial_r2 = (shipped.get("spatial_cv") or {}).get(
        "r2", (shipped.get("spatial_cv") or {}).get("rmse_r2")
    )
    random_r2 = (shipped.get("random_cv") or {}).get(
        "r2", (shipped.get("random_cv") or {}).get("rmse_r2")
    )

    target_note = metrics.get(
        "target_note",
        "Predicts ASKING price, not transaction price. Karnataka does not "
        "publish transaction prices, so asking prices carry a systematic "
        "upward bias of unknown size.",
    )
    caveats = [
        target_note,
        "Training data is a public dataset of uncertain vintage and "
        "unconfirmed licence. Not current market data.",
        f"Selected on spatial-block cross-validation (R2={spatial_r2}). Random "
        f"k-fold on the same data reports R2={random_r2}; the difference is "
        "leakage between neighbouring properties.",
        "The model has no metro distance, road width, floor or age features. "
        "Location is represented only at corporation level.",
    ]

    base = SourceRef(
        source_id=_source().source_id,
        name=f"{_source().name} - {metrics.get('model', 'model')}",
        organisation=_source().organisation,
        source_url=_source().source_url,
        tier=Tier.T4,
        source_updated=_source().source_updated,
        licence=_source().licence,
    )

    # Confidence is bounded twice: by the T4 tier ceiling and by an explicit
    # market ceiling, then scaled by how wide the interval is relative to the
    # point estimate. A band of +/-50% should not read as confident.
    relative_width = q / point if point > 0 else 1.0
    conf = min(MAX_MARKET_CONFIDENCE, 0.55 * max(0.0, 1.0 - relative_width))

    facts["price_per_sqft"] = Fact.observed(
        round(point, 0),
        source=base,
        confidence=conf,
        unit="INR/sq.ft (asking)",
        status=Status.ESTIMATED,
        caveats=caveats,
    )
    facts["price_range_low"] = Fact.observed(
        round(low, 0), source=base, confidence=conf,
        unit="INR/sq.ft", status=Status.ESTIMATED,
        caveats=["Lower bound of the 90% conformal prediction interval"],
    )
    facts["price_range_high"] = Fact.observed(
        round(high, 0), source=base, confidence=conf,
        unit="INR/sq.ft", status=Status.ESTIMATED,
        caveats=["Upper bound of the 90% conformal prediction interval"],
    )

    facts["estimated_value"] = Fact.derive(
        round(point * inp.sqft, 0),
        inputs=[facts["price_per_sqft"]],
        method=Method.ML_PREDICTION,
        assumptions=[
            f"Plot/built-up area of {inp.sqft:,.0f} sq.ft as supplied",
            "Value = predicted asking rate x area; no adjustment for floor, "
            "age, view, condition or amenities",
        ],
        unit="INR (indicative asking value)",
        status=Status.ESTIMATED,
    )

    # These two were hard-coded UNAVAILABLE before market_reference existed.
    # They now reflect what is actually held: a guidance value if someone has
    # recorded one by hand, and real recorded sale prices for Chennai.
    facts["guidance_value"] = _guidance_fact(city, inp.locality)
    facts["transaction_price"] = _transaction_fact(city, inp.locality)

    return facts


def _guidance_source(portal_name: str, url: str) -> SourceRef:
    """The portal a person transcribed the value from.

    Tier T2 rather than T1: the instrument is official, but the platform did
    not retrieve it — a human typed it in, and transcription is a real risk.
    """
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, url or portal_name),
        name=f"{portal_name} — value transcribed by hand",
        organisation=portal_name,
        source_url=url or None,
        tier=Tier.T2,
        licence="Official portal; value recorded manually by a user",
    )


def _dataset_source(city: str) -> SourceRef:
    """The city dataset the recorded sale prices come from."""
    meta = _metrics(city).get("dataset", {})
    url = meta.get("source_url", f"{city}-dataset")
    return SourceRef(
        source_id=uuid5(NAMESPACE_URL, url),
        name=f"{city.title()} property dataset — recorded sale prices",
        organisation="Public dataset (not a government register)",
        source_url=url,
        tier=Tier.T4,
        licence="As published by the dataset host",
    )


def _guidance_fact(city: str, locality: str | None) -> Fact[Any]:
    """A manually recorded guidance value, or an explanation of how to get one."""
    from app.services import market_reference

    look = market_reference.guidance_lookup(city, locality)
    if not look.get("available"):
        return Fact.unavailable(
            f"{look.get('reason', '')} {look.get('how_to_obtain', '')} "
            "Record it in the Market tab once you have it — the platform stores "
            "what a person looked up, attributed to them."
        )

    portal = look.get("portal", {})
    return Fact.observed(
        look["value_per_sqft"],
        source=_guidance_source(portal.get("name", "Official portal"),
                                portal.get("url", "")),
        confidence=0.55,
        status=Status.INDICATIVE,
        unit="INR per sq.ft",
        caveats=[
            f"MANUAL ENTRY recorded by {look.get('recorded_by')} from "
            f"{look.get('source_portal')}. Never VERIFIED — the platform did "
            "not retrieve it.",
            look.get("caveat", ""),
        ],
    )


def _transaction_fact(city: str, locality: str | None) -> Fact[Any]:
    """Real recorded sale prices, where the city's dataset is transactions."""
    from app.services import market_reference

    ref = market_reference.transaction_reference(city)
    if not ref.get("available"):
        return Fact.unavailable(
            f"{ref.get('reason', '')} {ref.get('alternative', '')}"
        )

    rows = ref.get("localities", [])
    match = None
    if locality:
        key = locality.strip().lower()
        match = next((r for r in rows
                      if r["locality"].strip().lower() == key), None)

    if match:
        value = match["median_price_per_sqft"]
        detail = (f"{match['locality']}: median of {match['recorded_sales']:,} "
                  f"recorded sales, {match['period']}")
    else:
        values = sorted(r["median_price_per_sqft"] for r in rows)
        value = values[len(values) // 2]
        detail = (f"Median across {len(rows)} localities and "
                  f"{ref.get('total_sales', 0):,} recorded sales. No locality "
                  "was supplied, so this is a city-wide figure.")

    return Fact.observed(
        value,
        source=_dataset_source(city),
        confidence=0.55,
        status=Status.INDICATIVE,
        unit="INR per sq.ft",
        caveats=[detail, ref.get("caveat", ""), ref.get("note", "")],
    )


def report(facts: dict[str, Fact[Any]]):
    return build_report({Category.MARKET: facts})


def explain(inp: ValuationInput) -> list[dict[str, Any]]:
    """Global feature attribution for the shipped model.

    Permutation importance on the spatially-honest test split rather than
    impurity importance, which is biased toward high-cardinality features.
    SHAP per-prediction attribution is Phase 9b.
    """
    return _metrics().get("permutation_importance", [])
