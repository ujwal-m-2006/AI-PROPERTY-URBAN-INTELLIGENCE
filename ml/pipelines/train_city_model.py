"""Multi-city ML pipeline — the complete lifecycle in one run.

    load -> clean -> EDA -> GIS feature engineering -> split
         -> 6 algorithms -> spatial-block CV -> tuning
         -> conformal intervals -> SHAP -> persist

Runs per city and never pools the two datasets.

    python ml/pipelines/train_city_model.py bengaluru
    python ml/pipelines/train_city_model.py chennai

Artifacts land in models/<city>/ and ml/artifacts/<city>/.

The existing ml/pipelines/train_price_model.py is left untouched so the original
Bengaluru result stays reproducible.
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.compose import ColumnTransformer  # noqa: E402
from sklearn.dummy import DummyRegressor  # noqa: E402
from sklearn.ensemble import (  # noqa: E402
    GradientBoostingRegressor,
    HistGradientBoostingRegressor,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.linear_model import LinearRegression  # noqa: E402
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score  # noqa: E402
from sklearn.model_selection import (  # noqa: E402
    GroupKFold,
    KFold,
    RandomizedSearchCV,
    train_test_split,
)
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.gis_features import add_gis_features  # noqa: E402
from pipelines import city_config  # noqa: E402

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
RANDOM_STATE = 42
CONFORMAL_ALPHA = 0.10

GIS_NUMERIC = [
    "metro_distance_m", "railway_distance_m", "bus_distance_m",
    "hospital_distance_m", "school_distance_m", "college_distance_m",
    "govt_office_distance_m", "bank_distance_m", "park_distance_m",
    "supermarket_distance_m", "amenity_count_1km",
]


# ----------------------------------------------------------------- EDA


def run_eda(df: pd.DataFrame, cfg, outdir: Path) -> dict[str, Any]:
    outdir.mkdir(parents=True, exist_ok=True)
    target = cfg.target

    numeric = df.select_dtypes(include=[np.number])
    report: dict[str, Any] = {
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "dtypes": {k: str(v) for k, v in df.dtypes.astype(str).items()},
        "missing_values": {
            k: int(v) for k, v in df.isna().sum().items() if v > 0
        },
        "duplicate_rows": int(df.duplicated().sum()),
        "target": {
            "name": target,
            "mean": round(float(df[target].mean()), 2),
            "median": round(float(df[target].median()), 2),
            "std": round(float(df[target].std()), 2),
            "min": round(float(df[target].min()), 2),
            "max": round(float(df[target].max()), 2),
            "skew": round(float(df[target].skew()), 3),
        },
    }

    q1, q3 = df[target].quantile([0.25, 0.75])
    iqr = q3 - q1
    outliers = df[(df[target] < q1 - 1.5 * iqr) | (df[target] > q3 + 1.5 * iqr)]
    report["target_outliers_iqr"] = int(len(outliers))

    # Exclude the target's own components. `price` correlating with
    # `price_per_sqft` is arithmetic, not a finding.
    leak = set(cfg.leakage_columns)
    corr_cols = [
        c for c in numeric.columns
        if numeric[c].notna().sum() > 50 and (c == target or c not in leak)
    ]
    corr = numeric[corr_cols].corr(numeric_only=True)
    report["excluded_from_correlation"] = sorted(leak & set(numeric.columns) - {target})
    report["correlation_with_target"] = {
        k: round(float(v), 4)
        for k, v in corr[target].drop(target, errors="ignore")
        .sort_values(key=abs, ascending=False)
        .head(15)
        .items()
    }

    loc = cfg.locality_column
    by_loc = (
        df.groupby(loc)[target]
        .agg(["count", "mean", "median"])
        .sort_values("count", ascending=False)
        .head(15)
    )
    report["top_localities"] = {
        str(k): {"count": int(r["count"]), "mean_psf": round(float(r["mean"]), 0)}
        for k, r in by_loc.iterrows()
    }

    # --- plots ---
    plt.figure(figsize=(7, 4))
    plt.hist(df[target].dropna(), bins=60, color="#9E1B1B", edgecolor="white")
    plt.title(f"{cfg.display} — {cfg.target_label}")
    plt.xlabel(cfg.target_label); plt.ylabel("Properties")
    plt.tight_layout(); plt.savefig(outdir / "target_distribution.png", dpi=110); plt.close()

    top = corr[target].drop(target, errors="ignore").abs().sort_values(ascending=False).head(12).index
    sub = corr.loc[list(top) + [target], list(top) + [target]]
    plt.figure(figsize=(8, 6.5))
    plt.imshow(sub, cmap="RdBu_r", vmin=-1, vmax=1)
    plt.colorbar(label="Pearson r")
    plt.xticks(range(len(sub)), sub.columns, rotation=90, fontsize=7)
    plt.yticks(range(len(sub)), sub.index, fontsize=7)
    plt.title(f"{cfg.display} — correlation")
    plt.tight_layout(); plt.savefig(outdir / "correlation_heatmap.png", dpi=110); plt.close()

    plt.figure(figsize=(8, 4.5))
    names = [str(k)[:18] for k in by_loc.index][::-1]
    plt.barh(names, by_loc["mean"].values[::-1], color="#1B365D")
    plt.title(f"{cfg.display} — mean {cfg.target_label} by locality (top 15 by volume)")
    plt.xlabel(cfg.target_label)
    plt.tight_layout(); plt.savefig(outdir / "price_by_locality.png", dpi=110); plt.close()

    report["plots"] = [
        "target_distribution.png", "correlation_heatmap.png", "price_by_locality.png"
    ]
    return report


# -------------------------------------------------------------- modelling


def build_pipeline(estimator, numeric: list[str], categorical: list[str]) -> Pipeline:
    return Pipeline([
        ("prep", ColumnTransformer([
            ("num", Pipeline([
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
            ]), numeric),
            ("cat", Pipeline([
                ("impute", SimpleImputer(strategy="constant", fill_value="unknown")),
                ("oh", OneHotEncoder(handle_unknown="ignore", min_frequency=15,
                                     sparse_output=False)),
            ]), categorical),
        ], remainder="drop")),
        ("model", estimator),
    ])


def metrics(actual, pred) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(actual, pred)), 1),
        "rmse": round(float(np.sqrt(mean_squared_error(actual, pred))), 1),
        "r2": round(float(r2_score(actual, pred)), 4),
        "mape_pct": round(float(np.mean(np.abs((actual - pred) / actual)) * 100), 2),
    }


def cross_validate(estimator, X, y, groups, scheme: str,
                   numeric: list[str], categorical: list[str]) -> dict[str, float]:
    splitter = (KFold(5, shuffle=True, random_state=RANDOM_STATE)
                if scheme == "random" else GroupKFold(n_splits=5))
    args = (X, y) if scheme == "random" else (X, y, groups)

    scores = []
    for tr, te in splitter.split(*args):
        m = build_pipeline(
            estimator.__class__(**estimator.get_params()), numeric, categorical
        )
        m.fit(X.iloc[tr], y.iloc[tr])
        scores.append(metrics(y.iloc[te], m.predict(X.iloc[te])))
    return {k: round(float(np.mean([s[k] for s in scores])), 4) for k in scores[0]}


def main() -> int:
    city = (sys.argv[1] if len(sys.argv) > 1 else "bengaluru").strip().lower()
    cfg = city_config.get(city)

    art = ROOT / "ml" / "artifacts" / city
    models_dir = ROOT / "models" / city
    art.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 74}\n  {cfg.display.upper()} — ML PIPELINE\n{'=' * 74}")
    print(f"  target: {cfg.target_label}")
    print(f"  note  : {cfg.target_note}\n")

    # 1. load + clean
    print("[1] LOAD + CLEAN")
    raw = city_config.load_raw(cfg)
    df, clean_log = cfg.clean(raw)
    for line in clean_log:
        print(f"    {line}")

    # 2. GIS feature engineering
    print("\n[2] GIS FEATURE ENGINEERING")
    df, gis_report = add_gis_features(
        df, locality_column=cfg.locality_column, city=city,
        amenities_file=cfg.amenities_file, wards_file=cfg.wards_file,
    )
    print(f"    gazetteer localities   : {gis_report['gazetteer_size']:,}")
    print(f"    locality match rate    : {gis_report['locality_match_rate']:.1%}")
    print(f"    ward match rate        : {gis_report['ward_match_rate']:.1%}")
    print(f"    amenity features used  : {gis_report['amenity_features']:,}")
    df["has_gis"] = df["gis_lat"].notna().astype(int)

    # 3. EDA
    print("\n[3] EDA")
    eda = run_eda(df, cfg, art / "eda")
    print(f"    rows {eda['rows']:,} | cols {eda['columns']} | "
          f"dupes {eda['duplicate_rows']} | target skew {eda['target']['skew']}")
    print("    top correlations: " + ", ".join(
        f"{k}={v}" for k, v in list(eda["correlation_with_target"].items())[:4]))

    # 4. features + split
    numeric = [c for c in cfg.numeric_features if c in df.columns]
    numeric += [c for c in GIS_NUMERIC if c in df.columns]
    numeric += ["has_gis"]
    categorical = [c for c in cfg.categorical_features if c in df.columns]
    if "gis_corporation" in df.columns and df["gis_corporation"].notna().any():
        categorical.append("gis_corporation")
    if "gis_zone" in df.columns and df["gis_zone"].notna().any():
        categorical.append("gis_zone")

    # Hard leakage guard. Fails the run rather than quietly training on the
    # target's own components and reporting an inflated score.
    leaked = sorted(set(numeric + categorical) & set(cfg.leakage_columns))
    if leaked:
        raise SystemExit(
            f"TARGET LEAKAGE: {leaked} are components of the target "
            f"{cfg.target!r} and must not be features."
        )

    X, y = df[numeric + categorical], df[cfg.target]
    groups = df["gis_ward_no"].astype("object").where(
        df["gis_ward_no"].notna(), "loc:" + df[cfg.locality_column].astype(str)
    ).astype(str)

    X_tr, X_tmp, y_tr, y_tmp, g_tr, g_tmp = train_test_split(
        X, y, groups, test_size=0.30, random_state=RANDOM_STATE)
    X_cal, X_te, y_cal, y_te = train_test_split(
        X_tmp, y_tmp, test_size=0.50, random_state=RANDOM_STATE)

    print("\n[4] FEATURES + SPLIT")
    print(f"    numeric {len(numeric)} | categorical {len(categorical)} | "
          f"GIS-derived {len([c for c in GIS_NUMERIC if c in numeric])}")
    print(f"    train {len(X_tr):,} | calibration {len(X_cal):,} | test {len(X_te):,}")
    print(f"    spatial blocks: {groups.nunique():,}")

    # 5. models
    import xgboost as xgb
    candidates = {
        "baseline_median": DummyRegressor(strategy="median"),
        "linear_regression": LinearRegression(),
        "random_forest": RandomForestRegressor(
            n_estimators=200, min_samples_leaf=3, n_jobs=-1, random_state=RANDOM_STATE),
        "gradient_boosting": GradientBoostingRegressor(random_state=RANDOM_STATE),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.08, random_state=RANDOM_STATE),
        "xgboost": xgb.XGBRegressor(
            n_estimators=400, learning_rate=0.06, max_depth=6, subsample=0.9,
            colsample_bytree=0.9, random_state=RANDOM_STATE, n_jobs=-1,
            tree_method="hist"),
    }

    print("\n[5] MODEL COMPARISON  (random k-fold vs spatial-block CV)")
    print(f"    {'model':<24}{'rand R2':>9}{'spatial R2':>12}{'gap':>9}"
          f"{'MAE':>10}{'RMSE':>10}{'MAPE%':>8}")
    print("    " + "-" * 82)

    results: dict[str, Any] = {}
    for name, est in candidates.items():
        rnd = cross_validate(est, X, y, groups, "random", numeric, categorical)
        spa = cross_validate(est, X, y, groups, "spatial", numeric, categorical)
        gap = round(rnd["r2"] - spa["r2"], 4)
        results[name] = {"random_cv": rnd, "spatial_cv": spa, "leakage_gap_r2": gap}
        print(f"    {name:<24}{rnd['r2']:>9.4f}{spa['r2']:>12.4f}{gap:>+9.4f}"
              f"{spa['mae']:>10,.0f}{spa['rmse']:>10,.0f}{spa['mape_pct']:>8.1f}")

    ranked = sorted(
        ((n, r) for n, r in results.items() if n != "baseline_median"),
        key=lambda kv: -kv[1]["spatial_cv"]["r2"])
    top2 = [n for n, _ in ranked[:2]]
    print(f"\n    top-2 on spatial CV: {', '.join(top2)}")

    # 6. hyperparameter tuning
    print("\n[6] HYPERPARAMETER TUNING  (RandomizedSearchCV, spatial-block CV)")
    grids = {
        "random_forest": {
            "model__n_estimators": [200, 400, 600],
            "model__max_depth": [None, 12, 20, 30],
            "model__min_samples_leaf": [1, 2, 3, 5],
            "model__max_features": ["sqrt", 0.5, 1.0]},
        "gradient_boosting": {
            "model__n_estimators": [150, 300, 500],
            "model__learning_rate": [0.03, 0.06, 0.1],
            "model__max_depth": [2, 3, 4],
            "model__subsample": [0.8, 1.0]},
        "hist_gradient_boosting": {
            "model__max_iter": [200, 400, 600],
            "model__learning_rate": [0.03, 0.06, 0.1],
            "model__max_leaf_nodes": [15, 31, 63],
            "model__min_samples_leaf": [10, 20, 40]},
        "xgboost": {
            "model__n_estimators": [300, 500, 800],
            "model__learning_rate": [0.03, 0.06, 0.1],
            "model__max_depth": [4, 6, 8],
            "model__subsample": [0.8, 0.9, 1.0],
            "model__colsample_bytree": [0.7, 0.9, 1.0]},
    }

    tuned: dict[str, Any] = {}
    best_name, best_score, best_est = None, -np.inf, None
    for name in top2:
        if name not in grids:
            continue
        search = RandomizedSearchCV(
            build_pipeline(candidates[name], numeric, categorical),
            grids[name], n_iter=12, cv=GroupKFold(n_splits=4),
            scoring="r2", random_state=RANDOM_STATE, n_jobs=-1)
        search.fit(X_tr, y_tr, groups=g_tr)
        tuned[name] = {
            "best_params": {k.replace("model__", ""): v
                            for k, v in search.best_params_.items()},
            "best_cv_r2": round(float(search.best_score_), 4),
        }
        print(f"    {name:<24} tuned spatial CV R2 = {search.best_score_:.4f}")
        print(f"      {tuned[name]['best_params']}")
        if search.best_score_ > best_score:
            best_name, best_score, best_est = name, search.best_score_, search.best_estimator_

    # 7. final evaluation
    print(f"\n[7] FINAL MODEL: {best_name}")
    test_pred = best_est.predict(X_te)
    test_metrics = metrics(y_te, test_pred)
    print(f"    held-out test  MAE {test_metrics['mae']:,.0f} | "
          f"RMSE {test_metrics['rmse']:,.0f} | R2 {test_metrics['r2']} | "
          f"MAPE {test_metrics['mape_pct']}%")

    # The held-out test split is RANDOM, so it shares whatever geographic
    # leakage the spatial-block CV exposes. When a dataset covers few distinct
    # localities the test score can look near-perfect and mean very little.
    # Say so in the artifact rather than letting the number stand alone.
    n_blocks = int(groups.nunique())
    best_spatial = results[best_name]["spatial_cv"]["r2"]
    optimism = round(test_metrics["r2"] - best_spatial, 4)
    test_warning = None
    if n_blocks < 15 or optimism > 0.20:
        test_warning = (
            f"The held-out test R2 of {test_metrics['r2']} is measured on a "
            f"RANDOM split and is optimistic. Spatial-block CV over "
            f"{n_blocks} block(s) gives R2 {best_spatial}, a difference of "
            f"{optimism}. With this few distinct localities the model is mostly "
            f"interpolating within areas it has already seen; treat the "
            f"spatial-block figure as the honest estimate of generalisation."
        )
        print(f"\n    !! TEST-SCORE WARNING: only {n_blocks} spatial blocks. "
              f"Random-split R2 {test_metrics['r2']} vs spatial-block "
              f"R2 {best_spatial} (optimism {optimism:+.4f}).")

    cal_resid = np.abs(y_cal - best_est.predict(X_cal))
    q = float(np.quantile(cal_resid, 1 - CONFORMAL_ALPHA))
    coverage = float(np.mean(np.abs(y_te - test_pred) <= q))
    print(f"    conformal 90% interval  +/- Rs {q:,.0f}/sq.ft  "
          f"(measured coverage {coverage:.1%})")

    # plots
    plt.figure(figsize=(5.4, 5.2))
    plt.scatter(y_te, test_pred, s=8, alpha=0.35, color="#1B365D")
    lim = [float(min(y_te.min(), test_pred.min())), float(max(y_te.max(), test_pred.max()))]
    plt.plot(lim, lim, "--", color="#9E1B1B", linewidth=1.2)
    plt.xlabel("Actual"); plt.ylabel("Predicted")
    plt.title(f"{cfg.display} — actual vs predicted ({best_name})")
    plt.tight_layout(); plt.savefig(art / "actual_vs_predicted.png", dpi=110); plt.close()

    resid = y_te - test_pred
    plt.figure(figsize=(6.4, 4))
    plt.scatter(test_pred, resid, s=8, alpha=0.35, color="#1B365D")
    plt.axhline(0, color="#9E1B1B", linestyle="--", linewidth=1.2)
    plt.xlabel("Predicted"); plt.ylabel("Residual")
    plt.title(f"{cfg.display} — residuals")
    plt.tight_layout(); plt.savefig(art / "residuals.png", dpi=110); plt.close()

    names_all = numeric + categorical
    plt.figure(figsize=(7, 5))
    order = sorted(results.items(), key=lambda kv: kv[1]["spatial_cv"]["r2"])
    plt.barh([n for n, _ in order], [r["spatial_cv"]["r2"] for _, r in order],
             color="#1B365D", label="spatial-block CV")
    plt.barh([n for n, _ in order], [r["random_cv"]["r2"] for _, r in order],
             color="#E9A800", alpha=0.45, label="random k-fold")
    plt.xlabel("R2"); plt.legend(); plt.title(f"{cfg.display} — model comparison")
    plt.tight_layout(); plt.savefig(art / "model_comparison.png", dpi=110); plt.close()

    # 8. explainability
    print("\n[8] EXPLAINABLE AI")
    perm = permutation_importance(best_est, X_te, y_te, n_repeats=5,
                                  random_state=RANDOM_STATE, n_jobs=-1)
    importance = sorted(
        ({"feature": n, "importance": round(float(v), 5)}
         for n, v in zip(names_all, perm.importances_mean, strict=True)),
        key=lambda d: -d["importance"])
    print("    permutation importance (top 8):")
    for it in importance[:8]:
        print(f"      {it['feature']:<26}{it['importance']:>9.4f}")

    shap_summary: list[dict[str, Any]] = []
    try:
        import shap
        pre = best_est.named_steps["prep"]
        model = best_est.named_steps["model"]
        Xt = pre.transform(X_te.iloc[:400])
        feat_names = list(pre.get_feature_names_out())
        explainer = shap.TreeExplainer(model)
        sv = explainer.shap_values(Xt)
        mean_abs = np.abs(sv).mean(axis=0)
        shap_summary = sorted(
            ({"feature": f.split("__")[-1], "mean_abs_shap": round(float(v), 3)}
             for f, v in zip(feat_names, mean_abs, strict=True)),
            key=lambda d: -d["mean_abs_shap"])[:20]
        print("    SHAP mean|value| (top 6):")
        for it in shap_summary[:6]:
            print(f"      {it['feature']:<26}{it['mean_abs_shap']:>10.1f}")

        plt.figure(figsize=(7, 5))
        top_shap = shap_summary[:15][::-1]
        plt.barh([d["feature"][:26] for d in top_shap],
                 [d["mean_abs_shap"] for d in top_shap], color="#9E1B1B")
        plt.xlabel("mean |SHAP value|")
        plt.title(f"{cfg.display} — SHAP feature impact")
        plt.tight_layout(); plt.savefig(art / "shap_importance.png", dpi=110); plt.close()
    except Exception as exc:  # SHAP is optional, never fatal
        print(f"    SHAP unavailable: {type(exc).__name__}: {exc}")

    # 9. persist
    import joblib

    # Fit and save EVERY candidate on the training split, not just the winner.
    # This is what makes single-model / dual-model / multi-model prediction
    # possible at inference time, and lets the app name the model in use.
    print("\n[9] PERSISTING ALL CANDIDATE MODELS")
    saved: dict[str, Any] = {}
    for name, est in candidates.items():
        if name == "baseline_median":
            continue
        pipe = build_pipeline(est.__class__(**est.get_params()), numeric, categorical)
        pipe.fit(X_tr, y_tr)
        resid = np.abs(y_cal - pipe.predict(X_cal))
        qi = float(np.quantile(resid, 1 - CONFORMAL_ALPHA))
        preds = pipe.predict(X_te)
        joblib.dump({
            "pipeline": pipe, "conformal_q": qi,
            "features": {"numeric": numeric, "categorical": categorical},
            "algorithm": name, "city": city,
        }, models_dir / f"model_{name}.joblib")
        saved[name] = {
            "file": f"model_{name}.joblib",
            "test_metrics": metrics(y_te, preds),
            "conformal_half_width": round(qi, 1),
            "spatial_cv_r2": results[name]["spatial_cv"]["r2"],
        }
        print(f"    {name:<24} test R2 {saved[name]['test_metrics']['r2']:>7.4f} "
              f"| +/- {qi:>8,.0f}")

    joblib.dump({
        "pipeline": best_est,
        "conformal_q": q,
        "alpha": CONFORMAL_ALPHA,
        "features": {"numeric": numeric, "categorical": categorical},
        "target": cfg.target,
        "target_label": cfg.target_label,
        "city": city,
        "algorithm": best_name,
        "trained_at": datetime.now(UTC).isoformat(),
    }, models_dir / "price_model.joblib")

    payload = {
        "city": city,
        "display": cfg.display,
        "algorithm": best_name,
        "target": cfg.target,
        "target_label": cfg.target_label,
        "target_note": cfg.target_note,
        "dataset": {
            "source_url": cfg.source_url,
            "tier": cfg.tier,
            "rows_clean": int(len(df)),
            "train": int(len(X_tr)), "calibration": int(len(X_cal)), "test": int(len(X_te)),
            "spatial_blocks": int(groups.nunique()),
            "n_features": len(names_all),
            "n_gis_features": len([c for c in GIS_NUMERIC if c in numeric]),
        },
        "cleaning_log": clean_log,
        "gis": gis_report,
        "eda": eda,
        "model_comparison": results,
        "tuning": tuned,
        "final_test_metrics": test_metrics,
        "test_split_warning": test_warning,
        "honest_generalisation_r2": best_spatial,
        "conformal": {
            "alpha": CONFORMAL_ALPHA,
            "half_width": round(q, 1),
            "empirical_coverage": round(coverage, 4),
        },
        "saved_models": saved,
        "permutation_importance": importance,
        "shap_importance": shap_summary,
        "plots": [
            "actual_vs_predicted.png", "residuals.png", "model_comparison.png",
            "shap_importance.png", "eda/target_distribution.png",
            "eda/correlation_heatmap.png", "eda/price_by_locality.png",
        ],
        "trained_at": datetime.now(UTC).isoformat(),
    }
    (art / "metrics.json").write_text(json.dumps(payload, indent=2, default=str),
                                      encoding="utf-8")

    print("\n[9] SAVED")
    print(f"    model   : {models_dir / 'price_model.joblib'}")
    print(f"    metrics : {art / 'metrics.json'}")
    print(f"    plots   : {art}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
