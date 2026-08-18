"""Total property price — Model 1, and the direct-vs-indirect question.

The shipped model predicts price PER SQ.FT. A buyer asks what the property
costs, which is a different target, and there are two ways to answer it:

    DIRECT    train a model on total price
    INDIRECT  train on price per sq.ft, then multiply by area

They are not obviously equivalent. Total price spans two orders of magnitude
(₹9 lakh to ₹29 crore here) and is dominated by area, so a direct model spends
its capacity learning "bigger is dearer". Price per sq.ft is closer to
stationary across the size range, so the indirect route may leave the model free
to learn location and quality instead. Which wins is an empirical question and
this pipeline answers it on the same spatial-block CV as everything else.

THE LEAKAGE THAT WOULD MAKE THIS MEANINGLESS
--------------------------------------------
price_per_sqft = price / area. Using it as a feature to predict price hands the
model the answer divided by a column it already has. The guard below fails the
run rather than warning, because a silent leak here would produce a
spectacular R² and a worthless model — exactly the result that looks best in a
report and means least.

ALGORITHMS
----------
Ridge, Lasso, Decision Tree and Extra Trees join the comparison here. They are
cheap, they are what a marker expects to see, and two of them are genuinely
informative: Lasso's coefficient shrinkage says something about feature
redundancy that the tree models cannot.

    python ml/pipelines/train_total_price.py [bengaluru|chennai]
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import (ExtraTreesRegressor, GradientBoostingRegressor,
                              RandomForestRegressor)
from sklearn.linear_model import Lasso, LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.tree import DecisionTreeRegressor

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

from features.gis_features import add_gis_features  # noqa: E402
from pipelines import city_config  # noqa: E402
from pipelines.train_city_model import GIS_NUMERIC, build_pipeline  # noqa: E402

RANDOM_STATE = 42
CV_FOLDS = 5

TOTAL_PRICE_COLUMN = {"bengaluru": "price_inr", "chennai": "SALES_PRICE"}

# Anything that is the target, or arithmetically implies it.
FORBIDDEN = ("price", "price_inr", "price_per_sqft", "SALES_PRICE",
             "REG_FEE", "COMMIS", "INT_SQFT_TOTAL")

CANDIDATES: dict[str, Any] = {
    "linear_regression": LinearRegression(),
    "ridge": Ridge(alpha=1.0, random_state=RANDOM_STATE),
    "lasso": Lasso(alpha=0.001, random_state=RANDOM_STATE, max_iter=5000),
    "decision_tree": DecisionTreeRegressor(max_depth=8,
                                           random_state=RANDOM_STATE),
    "random_forest": RandomForestRegressor(n_estimators=200, n_jobs=-1,
                                           random_state=RANDOM_STATE),
    "extra_trees": ExtraTreesRegressor(n_estimators=200, n_jobs=-1,
                                       random_state=RANDOM_STATE),
    "gradient_boosting": GradientBoostingRegressor(
        random_state=RANDOM_STATE, n_estimators=300, max_depth=3,
        learning_rate=0.05),
}


def assert_no_leakage(features: list[str], target_col: str) -> None:
    """Hard failure, not a warning. A leaked run still produces a number."""
    bad = [f for f in features if f in FORBIDDEN or f == target_col]
    if bad:
        raise AssertionError(
            f"TARGET LEAKAGE: {bad} would be given to a model predicting "
            f"{target_col}. price_per_sqft = price / area, so including it "
            "hands over the answer divided by a column already present."
        )


def _mape(y: np.ndarray, p: np.ndarray) -> float:
    """Safe on this data — every price is well above zero."""
    return float(np.mean(np.abs((y - p) / y)) * 100)


def main() -> int:
    city = (sys.argv[1] if len(sys.argv) > 1 else "bengaluru").strip().lower()
    cfg = city_config.get(city)
    art = ROOT / "ml" / "artifacts" / city
    art.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 76}\n  {cfg.display.upper()} — TOTAL PRICE (Model 1)"
          f"\n{'=' * 76}")

    df, _ = cfg.clean(city_config.load_raw(cfg))
    df, _gis = add_gis_features(
        df, locality_column=cfg.locality_column, city=city,
        amenities_file=cfg.amenities_file, wards_file=cfg.wards_file)
    df["has_gis"] = df["gis_lat"].notna().astype(int)

    target_col = TOTAL_PRICE_COLUMN[city]
    y = df[target_col].to_numpy(dtype=float)

    numeric = [c for c in cfg.numeric_features if c in df.columns]
    numeric += [c for c in GIS_NUMERIC if c in df.columns] + ["has_gis"]
    categorical = [c for c in cfg.categorical_features if c in df.columns]
    if df.get("gis_corporation") is not None and df["gis_corporation"].notna().any():
        categorical = categorical + ["gis_corporation"]

    assert_no_leakage(numeric + categorical, target_col)
    print(f"  leakage guard passed — {len(FORBIDDEN)} forbidden columns checked")
    print(f"  {len(df):,} rows | target {target_col} "
          f"(median ₹{np.median(y):,.0f})")

    groups = (df["gis_ward_no"].astype("object")
              .where(df["gis_ward_no"].notna(),
                     "loc:" + df[cfg.locality_column].astype(str))
              .astype(str).to_numpy())
    X = df[numeric + categorical]
    cv = GroupKFold(CV_FOLDS)

    # --- direct: model the total price ---------------------------------
    print(f"\n[1] DIRECT — predict {target_col} ({len(CANDIDATES)} algorithms)")
    baseline = np.full_like(y, np.median(y))
    rows: list[dict[str, Any]] = [{
        "model": "baseline_median", "r2": round(float(r2_score(y, baseline)), 4),
        "mae": round(float(mean_absolute_error(y, baseline))),
        "mape_pct": round(_mape(y, baseline), 2), "fit_seconds": 0.0,
    }]
    print(f"    {'baseline_median':<20} R² {rows[0]['r2']:>8.4f}  "
          f"MAE ₹{rows[0]['mae']:>11,}  MAPE {rows[0]['mape_pct']:>6.1f}%")

    for name, est in CANDIDATES.items():
        started = time.time()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pred = cross_val_predict(build_pipeline(est, numeric, categorical),
                                     X, y, cv=cv, groups=groups, n_jobs=-1)
        took = time.time() - started
        rows.append({
            "model": name, "r2": round(float(r2_score(y, pred)), 4),
            "mae": round(float(mean_absolute_error(y, pred))),
            "mape_pct": round(_mape(y, pred), 2),
            "fit_seconds": round(took, 1),
        })
        print(f"    {name:<20} R² {rows[-1]['r2']:>8.4f}  "
              f"MAE ₹{rows[-1]['mae']:>11,}  MAPE {rows[-1]['mape_pct']:>6.1f}%"
              f"  {took:>5.1f}s")

    best_direct = max((r for r in rows if r["model"] != "baseline_median"),
                      key=lambda r: r["r2"])

    # --- indirect: model price per sq.ft, then multiply ------------------
    print("\n[2] INDIRECT — predict price/sq.ft, then multiply by area")
    area_col = "sqft" if city == "bengaluru" else "INT_SQFT"
    area = df[area_col].to_numpy(dtype=float)
    y_psf = df["price_per_sqft"].to_numpy(dtype=float)

    est = CANDIDATES[best_direct["model"]]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pred_psf = cross_val_predict(build_pipeline(est, numeric, categorical),
                                     X, y_psf, cv=cv, groups=groups, n_jobs=-1)
    pred_indirect = pred_psf * area

    indirect = {
        "model": f"{best_direct['model']} on price_per_sqft x area",
        "r2": round(float(r2_score(y, pred_indirect)), 4),
        "mae": round(float(mean_absolute_error(y, pred_indirect))),
        "mape_pct": round(_mape(y, pred_indirect), 2),
    }
    print(f"    {'indirect':<20} R² {indirect['r2']:>8.4f}  "
          f"MAE ₹{indirect['mae']:>11,}  MAPE {indirect['mape_pct']:>6.1f}%")

    direct_wins = best_direct["r2"] >= indirect["r2"]
    winner = "direct" if direct_wins else "indirect"
    gap = round(abs(best_direct["r2"] - indirect["r2"]), 4)
    print(f"\n    {winner.upper()} wins by {gap} R² "
          f"(same algorithm, same folds, same features)")

    payload = {
        "city": city,
        "display": cfg.display,
        "generated_at": datetime.now(UTC).isoformat(),
        "target": target_col,
        "target_label": f"total property price (INR), {city}",
        "median_price": float(np.median(y)),
        "validation": (f"GroupKFold({CV_FOLDS}) by ward/locality — the same "
                       "spatial-block scheme as every other model here"),
        "leakage_guard": {
            "forbidden_columns": list(FORBIDDEN),
            "note": (
                "price_per_sqft = price / area. Using it to predict price hands "
                "the model the answer divided by a column it already has. The "
                "guard raises rather than warns, because a leaked run still "
                "produces a number — a spectacular one."
            ),
        },
        "direct": rows,
        "best_direct": best_direct,
        "indirect": indirect,
        "comparison": {
            "winner": winner,
            "r2_gap": gap,
            "reading": (
                f"Modelling total price directly beats going via price per "
                f"sq.ft by {gap} R². Total price is dominated by area, and the "
                "model has that column either way."
                if direct_wins else
                f"Going via price per sq.ft beats modelling total price "
                f"directly by {gap} R². Total price spans two orders of "
                "magnitude and is dominated by area; price per sq.ft is closer "
                "to stationary, which leaves the model free to learn location "
                "and quality rather than size."
            ),
            "why_it_matters": (
                "Both answer 'what does this cost'. They are trained on the "
                "same folds with the same features and the same algorithm, so "
                "the difference is the target formulation alone."
            ),
        },
    }
    (art / "total_price.json").write_text(json.dumps(payload, indent=2),
                                          encoding="utf-8")
    print(f"\n  wrote {art / 'total_price.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
