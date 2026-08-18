"""Phase 9 — price model (Module 14).

WHAT THIS MODEL ACTUALLY PREDICTS
---------------------------------
Asking price per square foot, from a public listing dataset of unclear vintage.
It is NOT a valuation and NOT a transaction price. Karnataka does not publish
transaction prices (audit finding 6), so no model built on public data can
predict one. Asking prices sit systematically above transaction prices.

METHODOLOGICAL POINT OF THE EXERCISE
------------------------------------
Random k-fold cross-validation on geographic data leaks neighbouring properties
between folds and produces an R2 that looks excellent and means nothing. This
script reports random-CV and spatial-block-CV side by side. The gap between them
is the honest measure of how much of the "accuracy" was leakage.

Listings are grouped into blocks by GBA ward where the locality name can be
matched to one of the 369 official wards, and by locality otherwise.
"""

from __future__ import annotations

import json
import re
import sys
import warnings
from datetime import UTC, datetime
from difflib import get_close_matches
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, KFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "bengaluru_house_data.csv"
WARDS = ROOT / "data" / "processed" / "gba_wards.geojson"
OUT = ROOT / "ml" / "artifacts"

RANDOM_STATE = 42
CONFORMAL_ALPHA = 0.10  # 90% prediction intervals

# Plausibility bounds for Bengaluru asking prices, in rupees per sq.ft.
# Stated explicitly rather than derived from percentiles so the filter is
# reviewable rather than a black box.
MIN_PSF, MAX_PSF = 1_500, 40_000
MIN_SQFT_PER_ROOM = 300


# --- cleaning ------------------------------------------------------------


def parse_sqft(value: object) -> float | None:
    """total_sqft holds ranges ('1195 - 1440') and units ('34.46Sq. Meter')."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip()

    if "-" in text:
        parts = [p.strip() for p in text.split("-")]
        try:
            return (float(parts[0]) + float(parts[1])) / 2
        except (ValueError, IndexError):
            return None

    match = re.match(r"^([\d.]+)\s*(.*)$", text)
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None

    unit = match.group(2).lower().replace(" ", "").replace(".", "")
    factors = {"sqmeter": 10.7639, "perch": 272.25, "sqyards": 9.0,
               "acres": 43560.0, "cents": 435.6, "guntha": 1089.0,
               "grounds": 2400.0}
    return number * factors.get(unit, 1.0) if unit in factors or unit == "" else number


def parse_rooms(value: object) -> int | None:
    """size is '2 BHK' or '4 Bedroom'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    match = re.search(r"(\d+)", str(value))
    return int(match.group(1)) if match else None


# --- GBA ward matching ---------------------------------------------------


def load_ward_names() -> dict[str, dict[str, str]]:
    """Ward name -> {ward, corporation}, with the numeric prefix stripped."""
    if not WARDS.exists():
        return {}
    payload = json.loads(WARDS.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for feature in payload["features"]:
        props = feature["properties"]
        raw = props.get("ward_name") or ""
        clean = re.sub(r"^\s*\d+\s*-\s*", "", raw).strip().lower()
        if clean:
            out[clean] = {"ward": raw, "corporation": props.get("corporation") or ""}
    return out


def match_localities(localities: pd.Series, wards: dict[str, dict[str, str]]):
    """Fuzzy-match listing localities to official GBA ward names.

    Derived (T5): a locality name matching a ward name is evidence, not proof of
    location. Used only to form cross-validation blocks and as a coarse feature,
    never presented to a user as the ward a property sits in.
    """
    names = list(wards)
    cache: dict[str, dict[str, str] | None] = {}

    def match_one(loc: object) -> dict[str, str] | None:
        key = str(loc).strip().lower()
        if key in cache:
            return cache[key]
        hit = None
        if key in wards:
            hit = wards[key]
        else:
            close = get_close_matches(key, names, n=1, cutoff=0.86)
            if close:
                hit = wards[close[0]]
        cache[key] = hit
        return hit

    matched = localities.map(match_one)
    return (
        matched.map(lambda m: m["ward"] if m else None),
        matched.map(lambda m: m["corporation"] if m else None),
    )


# --- pipeline ------------------------------------------------------------


def build_dataset() -> tuple[pd.DataFrame, list[str]]:
    log: list[str] = []
    df = pd.read_csv(RAW)
    log.append(f"loaded {len(df):,} raw listing rows")

    df["sqft"] = df["total_sqft"].map(parse_sqft)
    df["rooms"] = df["size"].map(parse_rooms)
    df["price_inr"] = pd.to_numeric(df["price"], errors="coerce") * 100_000  # lakhs

    before = len(df)
    df = df.dropna(subset=["sqft", "rooms", "price_inr", "location"])
    log.append(f"dropped {before - len(df):,} rows missing sqft / rooms / price / location")

    before = len(df)
    df = df[df["sqft"] / df["rooms"] >= MIN_SQFT_PER_ROOM]
    log.append(
        f"dropped {before - len(df):,} rows under {MIN_SQFT_PER_ROOM} sq.ft per room "
        "(implausible listings)"
    )

    df["price_per_sqft"] = df["price_inr"] / df["sqft"]

    before = len(df)
    df = df[(df["price_per_sqft"] >= MIN_PSF) & (df["price_per_sqft"] <= MAX_PSF)]
    log.append(
        f"dropped {before - len(df):,} rows outside Rs {MIN_PSF:,}-{MAX_PSF:,}/sq.ft"
    )

    # Per-locality outlier trim: within a locality, prices should be comparable.
    before = len(df)
    stats = df.groupby("location")["price_per_sqft"].agg(["mean", "std", "count"])
    df = df.join(stats, on="location")
    keep = (df["count"] < 5) | (
        (df["price_per_sqft"] >= df["mean"] - 2 * df["std"].fillna(0))
        & (df["price_per_sqft"] <= df["mean"] + 2 * df["std"].fillna(0))
    )
    df = df[keep].drop(columns=["mean", "std", "count"])
    log.append(f"dropped {before - len(df):,} rows beyond 2 SD of their locality mean")

    df["location"] = df["location"].astype(str).str.strip()
    df["bath"] = pd.to_numeric(df["bath"], errors="coerce")
    df["balcony"] = pd.to_numeric(df["balcony"], errors="coerce")
    df["area_type"] = df["area_type"].astype(str).str.strip()
    df["ready_to_move"] = (
        df["availability"].astype(str).str.strip().str.lower() == "ready to move"
    ).astype(int)

    wards = load_ward_names()
    if wards:
        df["gba_ward"], df["gba_corporation"] = match_localities(df["location"], wards)
        rate = df["gba_ward"].notna().mean()
        log.append(
            f"matched {rate:.1%} of listings to one of the 369 official GBA wards "
            "by locality name (derived, T5)"
        )
    else:
        df["gba_ward"] = None
        df["gba_corporation"] = None
        log.append("GBA ward layer not found — spatial blocks fall back to locality")

    # Cross-validation block: official ward where known, locality otherwise.
    df["block"] = df["gba_ward"].fillna("loc:" + df["location"])

    log.append(f"final dataset: {len(df):,} rows, {df['block'].nunique():,} spatial blocks")
    return df.reset_index(drop=True), log


NUMERIC = ["sqft", "rooms", "bath", "balcony", "ready_to_move"]

# Two feature sets, run side by side, because the difference between them is the
# whole methodological point.
#
#   without_locality — the model must generalise to an area it has never seen.
#   with_locality    — the locality one-hot is available. This is what almost
#                      every published Bengaluru price-prediction project uses,
#                      and under random k-fold it scores far better. Under
#                      spatial-block CV the locality column is useless for the
#                      held-out blocks, so the score collapses back. The size of
#                      that collapse is the leakage that random CV was hiding.
FEATURE_SETS = {
    "without_locality": ["area_type", "gba_corporation"],
    "with_locality": ["area_type", "gba_corporation", "location"],
}
CATEGORICAL = FEATURE_SETS["without_locality"]


def make_model(estimator) -> Pipeline:
    return Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [
                        (
                            "num",
                            Pipeline(
                                [
                                    ("impute", SimpleImputer(strategy="median")),
                                    ("scale", StandardScaler()),
                                ]
                            ),
                            NUMERIC,
                        ),
                        (
                            "cat",
                            Pipeline(
                                [
                                    ("impute", SimpleImputer(strategy="constant", fill_value="unknown")),
                                    (
                                        "oh",
                                        OneHotEncoder(
                                            handle_unknown="ignore",
                                            min_frequency=20,
                                            sparse_output=False,  # HistGB needs dense
                                        ),
                                    ),
                                ]
                            ),
                            CATEGORICAL,
                        ),
                    ],
                    remainder="drop",
                ),
            ),
            ("model", estimator),
        ]
    )


def evaluate(model: Pipeline, X, y, groups, scheme: str) -> dict[str, float]:
    splitter = (
        KFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
        if scheme == "random"
        else GroupKFold(n_splits=5)
    )
    split_args = (X, y) if scheme == "random" else (X, y, groups)

    maes, r2s, mapes = [], [], []
    for train_idx, test_idx in splitter.split(*split_args):
        m = make_model(model.named_steps["model"].__class__(**model.named_steps["model"].get_params()))
        m.fit(X.iloc[train_idx], y.iloc[train_idx])
        pred = m.predict(X.iloc[test_idx])
        actual = y.iloc[test_idx]
        maes.append(mean_absolute_error(actual, pred))
        r2s.append(r2_score(actual, pred))
        mapes.append(float(np.mean(np.abs((actual - pred) / actual)) * 100))

    return {
        "mae": round(float(np.mean(maes)), 1),
        "rmse_r2": round(float(np.mean(r2s)), 4),
        "mape_pct": round(float(np.mean(mapes)), 2),
    }


def main() -> int:
    if not RAW.exists():
        print(f"missing {RAW}")
        return 1

    df, log = build_dataset()
    print("\n".join(f"  {line}" for line in log))

    global CATEGORICAL
    y = df["price_per_sqft"]
    groups = df["block"]

    candidates = {
        "baseline_median": DummyRegressor(strategy="median"),
        "linear_regression": LinearRegression(),
        "random_forest": RandomForestRegressor(
            n_estimators=200, min_samples_leaf=3, n_jobs=-1, random_state=RANDOM_STATE
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.08, random_state=RANDOM_STATE
        ),
    }

    all_results: dict[str, dict] = {}

    for set_name, cats in FEATURE_SETS.items():
        CATEGORICAL = cats
        X_fs = df[NUMERIC + cats]

        print(f"\n  === feature set: {set_name} ===")
        print("  model                    random-CV R2   spatial-CV R2   gap     spatial MAE")
        print("  " + "-" * 76)

        results = {}
        for name, est in candidates.items():
            pipe = make_model(est)
            rnd = evaluate(pipe, X_fs, y, groups, "random")
            spa = evaluate(pipe, X_fs, y, groups, "spatial")
            gap = round(rnd["rmse_r2"] - spa["rmse_r2"], 4)
            results[name] = {"random_cv": rnd, "spatial_cv": spa, "leakage_gap_r2": gap}
            print(
                f"  {name:<24} {rnd['rmse_r2']:>9.4f}   {spa['rmse_r2']:>13.4f}   "
                f"{gap:>+7.4f}   Rs {spa['mae']:>8,.0f}"
            )
        all_results[set_name] = results

    headline = all_results["with_locality"]["hist_gradient_boosting"]
    print(
        f"\n  LEAKAGE: with locality features, random k-fold reports R2="
        f"{headline['random_cv']['rmse_r2']:.4f} but spatial-block CV reports "
        f"R2={headline['spatial_cv']['rmse_r2']:.4f}."
    )
    print(
        f"  {headline['leakage_gap_r2']:.4f} of that 'accuracy' was neighbouring "
        "properties leaking across folds."
    )

    # Ship the model that must generalise to unseen areas, selected on its
    # spatial-block score — the only honest basis for choosing.
    CATEGORICAL = FEATURE_SETS["without_locality"]
    X = df[NUMERIC + CATEGORICAL]
    results = all_results["without_locality"]
    best_name = max(
        (n for n in results if n != "baseline_median"),
        key=lambda n: results[n]["spatial_cv"]["rmse_r2"],
    )
    print(f"\n  shipping: {best_name} (without_locality), selected on spatial-block CV")

    # --- conformal intervals ---------------------------------------------
    # Split conformal: fit on train, calibrate on held-out residuals. Gives
    # distribution-free coverage rather than assuming Gaussian errors.
    gss_train, gss_temp = train_test_split(
        df.index, test_size=0.40, random_state=RANDOM_STATE
    )
    calib_idx, test_idx = train_test_split(
        gss_temp, test_size=0.50, random_state=RANDOM_STATE
    )

    final = make_model(candidates[best_name])
    final.fit(X.loc[gss_train], y.loc[gss_train])

    calib_resid = np.abs(y.loc[calib_idx] - final.predict(X.loc[calib_idx]))
    q = float(np.quantile(calib_resid, 1 - CONFORMAL_ALPHA))

    test_pred = final.predict(X.loc[test_idx])
    covered = np.mean(np.abs(y.loc[test_idx] - test_pred) <= q)
    print(
        f"  conformal 90% interval: +/- Rs {q:,.0f}/sq.ft  "
        f"(empirical coverage on held-out test: {covered:.1%})"
    )

    # --- feature importance ----------------------------------------------
    perm = permutation_importance(
        final, X.loc[test_idx], y.loc[test_idx], n_repeats=5,
        random_state=RANDOM_STATE, n_jobs=-1,
    )
    names = NUMERIC + CATEGORICAL
    importance = sorted(
        ({"feature": n, "importance": round(float(v), 4)}
         for n, v in zip(names, perm.importances_mean)),
        key=lambda d: -d["importance"],
    )
    print("\n  permutation importance (spatial-honest test split):")
    for item in importance:
        print(f"    {item['feature']:<20} {item['importance']:>8.4f}")

    # --- persist ----------------------------------------------------------
    OUT.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump(
        {
            "pipeline": final,
            "conformal_q": q,
            "alpha": CONFORMAL_ALPHA,
            "features": {"numeric": NUMERIC, "categorical": CATEGORICAL},
            "target": "price_per_sqft_inr",
            "trained_at": datetime.now(UTC).isoformat(),
        },
        OUT / "price_model.joblib",
    )

    metrics = {
        "model": best_name,
        "target": "asking price per sq.ft (INR)",
        "trained_at": datetime.now(UTC).isoformat(),
        "n_rows": int(len(df)),
        "n_blocks": int(groups.nunique()),
        "ward_match_rate": round(float(df["gba_ward"].notna().mean()), 4),
        "shipped_feature_set": "without_locality",
        "results_by_feature_set": all_results,
        "conformal": {
            "alpha": CONFORMAL_ALPHA,
            "half_width_inr_per_sqft": round(q, 1),
            "empirical_coverage": round(float(covered), 4),
        },
        "permutation_importance": importance,
        "cleaning_log": log,
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\n  wrote {OUT / 'price_model.joblib'} and metrics.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
