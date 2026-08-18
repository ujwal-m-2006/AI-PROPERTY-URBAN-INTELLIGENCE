"""Cross-city transfer: does what drives price in one city drive it in the other?

Four experiments on a shared 16-feature vocabulary (see harmonise.py):

    A  Bengaluru -> Bengaluru      within-city baseline
    B  Chennai   -> Chennai        within-city baseline
    C  Bengaluru -> Chennai        transfer
    D  Chennai   -> Bengaluru      transfer

THE MEASUREMENT PROBLEM, AND WHAT IS DONE ABOUT IT
--------------------------------------------------
Bengaluru's target is ASKING price per sq.ft. Chennai's is RECORDED SALE price
per sq.ft, over a period ending around 2015. They are different quantities in
different years. Run C and D on raw rupees and the error is dominated by that
mismatch, not by whether the model learned anything transferable — and reporting
a large MAE as "the model does not generalise" would be a straightforward
misattribution.

So every transfer is scored twice:

  RAW    predict rupees directly. Expect this to be bad, and read it as a
         measure of how far apart the two price levels are.

  RANK   predict each property's percentile WITHIN its own city. Price level
         cancels out, and what remains is the question worth asking: do the
         same features identify an expensive property in both cities?

Spearman correlation is the headline for the rank version because it is
invariant to any monotonic difference in price level — exactly the nuisance the
raw version cannot escape.

A THIRD COMPARISON
------------------
Separate city models (A, B) versus one combined model, with and without a city
indicator. If the combined model wins, the cities share structure worth pooling;
if it loses, they do not, and that is equally a result.

    python ml/pipelines/train_cross_city.py
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
sys.path.insert(0, str(ROOT / "backend"))

from features.gis_features import add_gis_features  # noqa: E402
from pipelines import city_config, harmonise  # noqa: E402

RANDOM_STATE = 42
CV_FOLDS = 5


def _estimator() -> Pipeline:
    """One algorithm across every experiment, so differences are the data."""
    return Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("model", GradientBoostingRegressor(
            random_state=RANDOM_STATE, n_estimators=300, max_depth=3,
            learning_rate=0.05)),
    ])


def load_city(city: str) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    cfg = city_config.get(city)
    df, _ = cfg.clean(city_config.load_raw(cfg))
    df, _gis = add_gis_features(
        df, locality_column=cfg.locality_column, city=city,
        amenities_file=cfg.amenities_file, wards_file=cfg.wards_file)

    X = harmonise.to_shared(df, city)
    y = df[cfg.target].to_numpy(dtype=float)
    groups = (df["gis_ward_no"].astype("object")
              .where(df["gis_ward_no"].notna(),
                     "loc:" + df[cfg.locality_column].astype(str))
              .astype(str).to_numpy())

    keep = np.isfinite(y) & X.notna().any(axis=1).to_numpy()
    return X[keep].reset_index(drop=True), y[keep], groups[keep]


def _to_rank(y: np.ndarray) -> np.ndarray:
    """Percentile within this city. Removes the price-level difference."""
    return pd.Series(y).rank(pct=True).to_numpy()


def within_city(X, y, groups, label: str) -> dict[str, Any]:
    """Honest within-city baseline: spatial-block CV, never a random split."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pred = cross_val_predict(_estimator(), X, y, cv=GroupKFold(CV_FOLDS),
                                 groups=groups, n_jobs=-1)
    rho = spearmanr(y, pred).statistic
    print(f"    {label:<26} R² {r2_score(y, pred):>7.4f}   "
          f"MAE {mean_absolute_error(y, pred):>9,.0f}   rho {rho:>6.3f}")
    return {
        "experiment": label,
        "kind": "within-city",
        "n": int(len(y)),
        "r2": round(float(r2_score(y, pred)), 4),
        "mae": round(float(mean_absolute_error(y, pred)), 1),
        "spearman": round(float(rho), 4),
        "validation": f"GroupKFold({CV_FOLDS}) by ward/locality",
    }


def transfer(Xa, ya, Xb, yb, label: str) -> dict[str, Any]:
    """Train on city A, test on city B — raw rupees and within-city rank."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = _estimator().fit(Xa, ya)
        pred_raw = raw.predict(Xb)

        rank = _estimator().fit(Xa, _to_rank(ya))
        pred_rank = rank.predict(Xb)

    yb_rank = _to_rank(yb)
    rho_raw = spearmanr(yb, pred_raw).statistic
    rho_rank = spearmanr(yb_rank, pred_rank).statistic

    print(f"    {label:<26} RAW  R² {r2_score(yb, pred_raw):>8.4f}  "
          f"MAE {mean_absolute_error(yb, pred_raw):>9,.0f}")
    print(f"    {'':<26} RANK rho {rho_rank:>7.3f}  "
          f"R² {r2_score(yb_rank, pred_rank):>7.4f}")

    return {
        "experiment": label,
        "kind": "transfer",
        "n_train": int(len(ya)),
        "n_test": int(len(yb)),
        "raw": {
            "r2": round(float(r2_score(yb, pred_raw)), 4),
            "mae": round(float(mean_absolute_error(yb, pred_raw)), 1),
            "spearman": round(float(rho_raw), 4),
            "reading": (
                "Predicting the other city's price level directly. The targets "
                "measure different things, so a poor score here is mostly that "
                "mismatch and must not be read as the model failing to learn."
            ),
        },
        "rank": {
            "r2": round(float(r2_score(yb_rank, pred_rank)), 4),
            "spearman": round(float(rho_rank), 4),
            "reading": (
                "Predicting within-city percentile, so price level cancels. "
                "Spearman here answers the question that matters: do the same "
                "features identify an expensive property in both cities?"
            ),
        },
    }


def main() -> int:
    print(f"\n{'=' * 76}\n  CROSS-CITY TRANSFER — shared "
          f"{len(harmonise.SHARED_FEATURES)}-feature vocabulary\n{'=' * 76}")

    print("\n[0] LOADING ON THE SHARED SCHEMA")
    Xb, yb, gb = load_city("bengaluru")
    Xc, yc, gc = load_city("chennai")
    print(f"    bengaluru {len(yb):,} rows  |  chennai {len(yc):,} rows")
    print(f"    shared features: {', '.join(harmonise.SHARED_FEATURES[:5])} "
          f"... (+{len(harmonise.SHARED_FEATURES) - 5} more, 11 of them GIS)")
    print(f"    median target — bengaluru {np.median(yb):,.0f} (asking)  "
          f"chennai {np.median(yc):,.0f} (recorded sale)")

    print("\n[1] WITHIN-CITY BASELINES (A, B)")
    a = within_city(Xb, yb, gb, "A  bengaluru -> bengaluru")
    b = within_city(Xc, yc, gc, "B  chennai -> chennai")

    print("\n[2] TRANSFER (C, D)")
    c = transfer(Xb, yb, Xc, yc, "C  bengaluru -> chennai")
    d = transfer(Xc, yc, Xb, yb, "D  chennai -> bengaluru")

    print("\n[3] SEPARATE vs COMBINED")
    X_all = pd.concat([Xb, Xc], ignore_index=True)
    y_all = np.concatenate([yb, yc])
    g_all = np.concatenate([np.char.add("blr:", gb.astype(str)),
                            np.char.add("chn:", gc.astype(str))])
    combined = within_city(X_all, y_all, g_all, "combined, no city flag")

    X_flag = X_all.copy()
    X_flag["is_chennai"] = np.concatenate([np.zeros(len(yb)), np.ones(len(yc))])
    combined_flag = within_city(X_flag, y_all, g_all, "combined + city flag")

    # Pooling two different targets inflates variance, which inflates R².
    # Comparing that against a single-city R² would be arithmetic, not a finding.
    weighted = (a["r2"] * len(yb) + b["r2"] * len(yc)) / (len(yb) + len(yc))
    weighted_mae = ((a["mae"] * len(yb) + b["mae"] * len(yc))
                    / (len(yb) + len(yc)))
    print(f"    {'separate (size-weighted)':<26} R² {weighted:>7.4f}   "
          f"MAE {weighted_mae:>9,.0f}")

    # The tell. If pooling genuinely helped, MAE would fall with R². It does not:
    # R² rises only because pooling two price levels widens the variance the
    # model is scored against.
    r2_gain = combined_flag["r2"] - weighted
    mae_change = combined_flag["mae"] - weighted_mae
    print("")
    print(f"    combined vs separate:  R² {r2_gain:+.4f}   "
          f"MAE {mae_change:+,.0f}")
    if r2_gain > 0.01 and mae_change > -50:
        print("    => R² improved while MAE did not. That is variance inflation")
        print("       from pooling two different targets, not a better model.")

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "shared_schema": harmonise.describe(),
        "estimator": "GradientBoostingRegressor, identical across all experiments",
        "within_city": [a, b],
        "transfer": [c, d],
        "separate_vs_combined": {
            "separate_weighted_r2": round(float(weighted), 4),
            "separate_weighted_mae": round(float(weighted_mae), 1),
            "combined_mae": combined["mae"],
            "combined_with_city_flag_mae": combined_flag["mae"],
            "r2_gain": round(float(r2_gain), 4),
            "mae_change": round(float(mae_change), 1),
            "verdict": (
                "R² improved while MAE did not. Pooling two different targets "
                "widens the variance R² is measured against, so the apparent "
                "gain is arithmetic. MAE, which is in rupees and immune to that, "
                "is flat — the combined model is not better."
                if (r2_gain > 0.01 and mae_change > -50) else
                "R² and MAE moved together, so the comparison is meaningful."
            ),
            "combined_r2": combined["r2"],
            "combined_with_city_flag_r2": combined_flag["r2"],
            "caveat": (
                "The combined model is fitted across two different targets — "
                "asking price and recorded sale price. Pooling them widens the "
                "spread of y, and R² rises with the variance it has to explain. "
                "A higher combined R² is therefore NOT evidence that pooling "
                "helps, and is reported here only so the comparison is not "
                "silently omitted."
            ),
        },
        "how_to_read": (
            "The RANK results are the interpretable ones. Raw transfer is "
            "dominated by the difference between asking and recorded-sale "
            "prices, which no amount of feature harmonising can remove."
        ),
    }

    for city in ("bengaluru", "chennai"):
        out = ROOT / "ml" / "artifacts" / city
        out.mkdir(parents=True, exist_ok=True)
        (out / "cross_city.json").write_text(json.dumps(payload, indent=2),
                                             encoding="utf-8")

    print(f"\n  wrote ml/artifacts/<city>/cross_city.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
