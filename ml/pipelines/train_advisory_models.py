"""Advisory models — the questions a buyer, seller and investor actually ask.

The shipped regression answers "what is this worth?". That is one question. The
three parties in a transaction each need a different one, and none of them is
answered by a single point estimate:

    BUYER    "What is a defensible offer, and what am I overpaying for?"
    SELLER   "What can I realistically ask, and what would move the price?"
    INVESTOR "How wide is the uncertainty, and is the spread worth the risk?"

Two models are trained here, both on the same spatial-block split the rest of
the project uses, so their numbers are comparable with the headline R².

1. QUANTILE REGRESSION (P10 / P50 / P90)
   Three gradient-boosting models under pinball loss. This gives a *negotiation
   band* — a defensible low offer, a midpoint, and an ambitious ask — rather
   than a single number with an error bar bolted on.

   Two things are checked rather than assumed:
     * **Quantile crossing.** Independently fitted quantiles can produce
       P10 > P90 for some rows, which is nonsense. The rate is measured and
       reported, and the band is sorted per row so a crossed prediction cannot
       reach a user.
     * **Measured coverage.** A P10–P90 band should contain ~80% of held-out
       actuals. The observed figure is reported next to the nominal one. If
       they diverge the band is miscalibrated, and saying so is the point.

2. PARTIAL DEPENDENCE
   What actually moves price, holding everything else fixed — the seller's
   "would another bathroom help?" and the builder's "what configuration".

   This is a **model-derived** answer, not a causal one. Partial dependence
   shows what the model learned from observational data; it does not show what
   would happen if you built another bathroom. That distinction is carried in
   the output and must survive into the UI.

    python ml/pipelines/train_advisory_models.py [bengaluru|chennai]
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import GradientBoostingRegressor  # noqa: E402
from sklearn.inspection import partial_dependence  # noqa: E402
from sklearn.model_selection import GroupShuffleSplit  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

from features.gis_features import add_gis_features  # noqa: E402
from pipelines import city_config  # noqa: E402
from pipelines.train_city_model import GIS_NUMERIC, build_pipeline  # noqa: E402

RANDOM_STATE = 42
QUANTILES = (0.10, 0.50, 0.90)

# Features a seller or builder can actually change, versus ones they cannot.
# Only the first group is worth a partial-dependence curve for advice.
ACTIONABLE = ("sqft", "bath", "rooms", "balcony", "area_per_room",
              "total_sqft", "N_BEDROOM", "N_BATHROOM", "INT_SQFT")

NOT_CAUSAL = (
    "THIS IS NOT A CAUSAL ESTIMATE. Partial dependence shows what the MODEL "
    "learned from observed data, not what would happen if you changed the "
    "property. Homes with more bathrooms differ in many other ways too, and "
    "the model cannot separate those. Read it as 'how the model responds', "
    "never as 'what adding one would earn'."
)


def _pinball(y_true: np.ndarray, y_pred: np.ndarray, q: float) -> float:
    """Pinball (quantile) loss — the correct scoring rule for a quantile."""
    d = y_true - y_pred
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def main() -> int:
    city = (sys.argv[1] if len(sys.argv) > 1 else "bengaluru").strip().lower()
    cfg = city_config.get(city)
    art = ROOT / "ml" / "artifacts" / city
    models_dir = ROOT / "models" / city
    art.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 72}\n  {cfg.display.upper()} — ADVISORY MODELS "
          f"(buyer / seller / investor)\n{'=' * 72}")

    df, _ = cfg.clean(city_config.load_raw(cfg))
    df, gis = add_gis_features(
        df, locality_column=cfg.locality_column, city=city,
        amenities_file=cfg.amenities_file, wards_file=cfg.wards_file)
    df["has_gis"] = df["gis_lat"].notna().astype(int)

    numeric = [c for c in cfg.numeric_features if c in df.columns]
    numeric += [c for c in GIS_NUMERIC if c in df.columns] + ["has_gis"]
    categorical = [c for c in cfg.categorical_features if c in df.columns]
    if df.get("gis_corporation") is not None and df["gis_corporation"].notna().any():
        categorical = categorical + ["gis_corporation"]

    groups = df["gis_ward_no"].astype("object").where(
        df["gis_ward_no"].notna(), "loc:" + df[cfg.locality_column].astype(str)
    ).astype(str)

    X = df[numeric + categorical]
    y = df[cfg.target].to_numpy()
    n_blocks = groups.nunique()
    print(f"  {len(df):,} rows | {n_blocks} spatial blocks | target {cfg.target}")

    # Three-way split, all by spatial block: fit / calibrate / test. The
    # calibration fold exists so the band can be conformalized (below) without
    # ever touching the test fold.
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25,
                                 random_state=RANDOM_STATE)
    fit_cal, te = next(splitter.split(X, y, groups=groups))
    g_fc = groups.iloc[fit_cal]
    inner = GroupShuffleSplit(n_splits=1, test_size=0.25,
                              random_state=RANDOM_STATE)
    f_rel, c_rel = next(inner.split(X.iloc[fit_cal], y[fit_cal], groups=g_fc))
    tr, cal = fit_cal[f_rel], fit_cal[c_rel]

    X_tr, X_cal, X_te = X.iloc[tr], X.iloc[cal], X.iloc[te]
    y_tr, y_cal, y_te = y[tr], y[cal], y[te]
    print(f"  fit {len(tr):,} / calibrate {len(cal):,} / test {len(te):,} — "
          "every split by spatial block, so no locality spans two folds")

    payload: dict[str, Any] = {
        "city": city,
        "display": cfg.display,
        "generated_at": datetime.now(UTC).isoformat(),
        "target": cfg.target,
        "target_label": getattr(cfg, "target_label", cfg.target),
        "split": "GroupShuffleSplit by locality/ward — no locality spans the split",
        "spatial_blocks": int(n_blocks),
    }

    # ------------------------------------------------ 1. quantile band
    print("\n[1] QUANTILE REGRESSION — negotiation band")
    preds: dict[str, np.ndarray] = {}
    fitted: dict[str, Any] = {}
    cal_preds: dict[str, np.ndarray] = {}
    losses: dict[str, float] = {}

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for q in QUANTILES:
            model = build_pipeline(
                GradientBoostingRegressor(
                    loss="quantile", alpha=q, random_state=RANDOM_STATE,
                    n_estimators=300, max_depth=3, learning_rate=0.05),
                numeric, categorical)
            model.fit(X_tr, y_tr)
            fitted[f"p{int(q * 100)}"] = model
            p = model.predict(X_te)
            preds[f"p{int(q * 100)}"] = p
            cal_preds[f"p{int(q * 100)}"] = model.predict(X_cal)
            losses[f"p{int(q * 100)}"] = _pinball(y_te, p, q)
            print(f"    P{int(q * 100):<3} pinball loss {losses[f'p{int(q * 100)}']:,.1f}")

    lo, mid, hi = preds["p10"], preds["p50"], preds["p90"]

    # Independently fitted quantiles can cross. Measure it, don't assume.
    crossed = int(np.sum(lo > hi))
    crossed_rate = crossed / len(y_te)
    band = np.sort(np.vstack([lo, mid, hi]), axis=0)      # enforce ordering
    lo_s, mid_s, hi_s = band[0], band[1], band[2]

    covered = float(np.mean((y_te >= lo_s) & (y_te <= hi_s)))
    width = float(np.median(hi_s - lo_s))
    median_price = float(np.median(y_te))

    # --- conformalize (CQR, Romano et al. 2019) --------------------------
    # Raw quantile regression under-covers on unseen localities: the model has
    # never seen the block, so its quantiles are too tight. CQR fixes this by
    # measuring, on a held-out calibration fold, how far outside the band the
    # truth actually falls, then widening by that amount. The guarantee is
    # distribution-free and needs no assumption about the error shape.
    cal_lo = np.minimum(cal_preds["p10"], cal_preds["p90"])
    cal_hi = np.maximum(cal_preds["p10"], cal_preds["p90"])
    # Conformity score: how far outside the band the actual fell (negative if inside).
    scores = np.maximum(cal_lo - y_cal, y_cal - cal_hi)
    alpha = 0.20                                   # 80% target coverage
    n_cal = len(scores)
    k = int(np.ceil((n_cal + 1) * (1 - alpha)))
    k = min(max(k, 1), n_cal)
    qhat = float(np.sort(scores)[k - 1])

    conf_lo, conf_hi = lo_s - qhat, hi_s + qhat
    conf_cov = float(np.mean((y_te >= conf_lo) & (y_te <= conf_hi)))
    conf_width = float(np.median(conf_hi - conf_lo))

    print(f"    conformal adjustment (qhat): {qhat:,.0f} from {n_cal:,} "
          "calibration rows")
    print(f"    CONFORMALIZED coverage : {conf_cov:.1%} "
          f"(target {1 - alpha:.0%})")
    print(f"    conformalized width    : {conf_width:,.0f} "
          f"({conf_width / median_price:.0%} of median)")
    conf_ok = abs(conf_cov - (1 - alpha)) <= 0.05
    conf_dir = ("on target" if conf_ok
                else "OVER-COVERS" if conf_cov > 1 - alpha else "UNDER-COVERS")
    # Calibration needs enough independent blocks to estimate a quantile of the
    # conformity scores. With a handful, qhat is driven by a few localities.
    few_blocks = n_blocks < 15
    if few_blocks:
        print(f"    WARNING: only {n_blocks} spatial blocks — the conformal "
              "adjustment is estimated from very few independent localities "
              "and should not be read as a coverage guarantee")

    # Why is it still short of 80%? Conformal prediction guarantees coverage
    # only if calibration and test rows are EXCHANGEABLE. A spatial split
    # deliberately breaks that: the test localities are ones the model has
    # never seen, drawn from a different part of the city. To show the
    # shortfall is the split and not a broken implementation, the same
    # procedure is rerun with a random calibration/test division, where
    # exchangeability does hold.
    rng = np.random.default_rng(RANDOM_STATE)
    pool_lo = np.concatenate([cal_lo, np.minimum(lo_s, hi_s)])
    pool_hi = np.concatenate([cal_hi, np.maximum(lo_s, hi_s)])
    pool_y = np.concatenate([y_cal, y_te])
    idx = rng.permutation(len(pool_y))
    half = len(idx) // 2
    a_i, b_i = idx[:half], idx[half:]
    s_rand = np.maximum(pool_lo[a_i] - pool_y[a_i], pool_y[a_i] - pool_hi[a_i])
    k_r = min(max(int(np.ceil((len(s_rand) + 1) * (1 - alpha))), 1), len(s_rand))
    qhat_rand = float(np.sort(s_rand)[k_r - 1])
    rand_cov = float(np.mean(
        (pool_y[b_i] >= pool_lo[b_i] - qhat_rand)
        & (pool_y[b_i] <= pool_hi[b_i] + qhat_rand)))
    print(f"    same method, RANDOM split : {rand_cov:.1%} "
          "(exchangeability holds there)")

    print(f"    quantile crossing : {crossed} of {len(y_te)} rows "
          f"({crossed_rate:.2%}) — sorted per row before use")
    print(f"    nominal coverage  : 80%  (P10-P90)")
    print(f"    MEASURED coverage : {covered:.1%}")
    print(f"    median band width : {width:,.0f} ({width / median_price:.0%} of "
          f"median price)")

    calibrated = abs(covered - 0.80) <= 0.05
    if not calibrated:
        print(f"    WARNING: measured coverage {covered:.1%} differs from the "
              "nominal 80% by more than 5 points — the band is miscalibrated "
              "and must be reported as such")

    payload["negotiation_band"] = {
        "method": "Gradient boosting under pinball (quantile) loss — supervised ML",
        "quantiles": [0.10, 0.50, 0.90],
        "pinball_loss": {k: round(v, 2) for k, v in losses.items()},
        "nominal_coverage": 0.80,
        "measured_coverage": round(covered, 4),
        "calibrated": bool(calibrated),
        "calibration_note": (
            f"A P10-P90 band should contain 80% of held-out actuals. It "
            f"contains {covered:.1%}. "
            + ("That is within 5 points, so the band is usable as stated."
               if calibrated else
               "That is more than 5 points away, so the band is MISCALIBRATED "
               "— treat its width as indicative only.")
        ),
        "quantile_crossing": {
            "rows": crossed,
            "rate": round(crossed_rate, 4),
            "handling": (
                "Independently fitted quantiles can produce P10 > P90. Every "
                "band is sorted per row before use, so a crossed prediction "
                "cannot reach a user."
            ),
        },
        "median_band_width": round(width),
        "median_band_width_pct_of_price": round(width / median_price, 3),
        "conformalized": {
            "method": ("Conformalized Quantile Regression (CQR) — the raw band "
                       "is widened by a constant learned on a held-out "
                       "calibration fold, giving distribution-free coverage"),
            "qhat": round(qhat, 1),
            "calibration_rows": int(n_cal),
            "target_coverage": round(1 - alpha, 2),
            "measured_coverage": round(conf_cov, 4),
            "calibrated": bool(conf_ok),
            "direction": conf_dir,
            "reliable": bool(conf_ok and not few_blocks),
            "few_blocks_warning": (
                f"Only {n_blocks} spatial blocks. The conformal adjustment is "
                "estimated from very few independent localities, so its "
                "coverage is not a guarantee — a band that covers 100% is "
                "over-conservative and uninformative, not accurate."
                if few_blocks else None
            ),
            "median_width": round(conf_width),
            "median_width_pct_of_price": round(conf_width / median_price, 3),
            "why": (
                f"Raw quantile regression covered {covered:.1%} against a "
                f"nominal 80% — it under-covers on localities the model never "
                f"saw. CQR widens the band to reach {conf_cov:.1%} "
                f"({conf_dir}). Where that lands on target the wider band is "
                "the honest one; where it overshoots, the band is too wide to "
                "be useful and says so."
            ),
            "use_this_one": True,
            "exchangeability_check": {
                "spatial_split_coverage": round(conf_cov, 4),
                "random_split_coverage": round(rand_cov, 4),
                "finding": (
                    f"The same conformal procedure reaches {rand_cov:.1%} under "
                    f"a random split but only {conf_cov:.1%} under the spatial "
                    "split. Conformal prediction guarantees coverage only when "
                    "calibration and test rows are exchangeable, and holding "
                    "out whole localities breaks that on purpose. The shortfall "
                    "is the honest cost of spatial validation, not a defect in "
                    "the method — and the spatial number is the one reported."
                ),
            },
        },
        "interpretation": {
            "buyer": ("P10 is a defensible opening offer — 10% of comparable "
                      "properties transact at or below it. Below P10 you are "
                      "arguing against the market."),
            "seller": ("P90 is an ambitious but evidenced ask — 10% achieve it. "
                       "P50 is the realistic midpoint."),
            "investor": ("Band width is the market's disagreement about this "
                         "property type in this area. A wide band means "
                         "comparable homes vary a lot, so entry price matters "
                         "more than the headline estimate."),
        },
        "caveat": (
            "These are quantiles of ASKING price where the city's dataset is "
            "listings, and of RECORDED SALE price where it is transactions. "
            "They are not a valuation and not a negotiating position endorsed "
            "by anyone."
        ),
    }

    # ------------------------------------------------ 2. partial dependence
    print("\n[2] PARTIAL DEPENDENCE — what moves the model's price")
    pd_model = build_pipeline(
        GradientBoostingRegressor(random_state=RANDOM_STATE, n_estimators=300,
                                  max_depth=3, learning_rate=0.05),
        numeric, categorical)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pd_model.fit(X_tr, y_tr)

    actionable = [c for c in ACTIONABLE if c in numeric]

    def _curve(model, feat):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = partial_dependence(model, X_te, [feat], kind="average",
                                     grid_resolution=12)
        return ([float(v) for v in res["grid_values"][0]],
                [float(v) for v in res["average"][0]])

    # A first run of this script gave `bath` a FALLING curve and a second gave
    # it a RISING one — on the same data, with a different fold. So the
    # stability test has to vary the FOLD, not just the estimator seed: a curve
    # that survives three seeds on one fixed training set proves nothing about
    # the failure actually observed. Each seed below therefore re-splits the
    # data (still by spatial block) and refits.
    SEEDS = (42, 7, 2024)
    seed_models = []
    for sd in SEEDS:
        sp = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=sd)
        tr_s, _te_s = next(sp.split(X, y, groups=groups))
        m = build_pipeline(
            GradientBoostingRegressor(random_state=sd, n_estimators=300,
                                      max_depth=3, learning_rate=0.05),
            numeric, categorical)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m.fit(X.iloc[tr_s], y[tr_s])
        seed_models.append(m)

    curves: list[dict[str, Any]] = []
    for feat in actionable[:5]:
        try:
            grid, avg = _curve(pd_model, feat)
            dirs, swings = [], []
            for m in seed_models:
                _g, a = _curve(m, feat)
                dirs.append("rises" if a[-1] > a[0] else
                            "falls" if a[-1] < a[0] else "flat")
                swings.append(max(a) - min(a))
        except Exception as exc:                              # noqa: BLE001
            print(f"    {feat}: skipped ({type(exc).__name__})")
            continue

        swing = max(avg) - min(avg)
        direction = ("rises" if avg[-1] > avg[0]
                     else "falls" if avg[-1] < avg[0] else "flat")
        stable = len(set(dirs)) == 1
        curves.append({
            "feature": feat,
            "grid": [round(g, 2) for g in grid],
            "predicted": [round(a, 1) for a in avg],
            "swing": round(swing, 1),
            "swing_pct_of_median": round(swing / median_price, 3),
            "direction": direction if stable else "UNSTABLE",
            "stable_across_seeds": bool(stable),
            "seed_directions": dirs,
            "seed_swing_range": [round(min(swings), 1), round(max(swings), 1)],
            "note": (
                "Direction is consistent across 3 independent spatial splits."
                if stable else
                "Direction FLIPS between seeds, so it carries no information. "
                "Reported as unstable rather than given a direction."
            ),
        })
        flag = "" if stable else "   <-- UNSTABLE, direction flips"
        print(f"    {feat:<20} swing {swing:>9,.0f} "
              f"({swing / median_price:>5.1%}) — {direction}{flag}")

    unstable = [c["feature"] for c in curves if not c["stable_across_seeds"]]
    if unstable:
        print(f"    {len(unstable)} of {len(curves)} curves are unstable: "
              f"{', '.join(unstable)}")
    curves.sort(key=lambda c: (not c["stable_across_seeds"], -c["swing"]))
    payload["what_moves_price"] = {
        "method": "Partial dependence on a gradient-boosting model — ML-derived",
        "features": curves,
        "stability": {
            "seeds_tested": list(SEEDS),
            "unstable_features": unstable,
            "note": (
                "Partial dependence on correlated features can flip direction "
                "with the training fold. Each curve was refit on 3 independent "
                "spatial-block splits; any feature whose direction disagreed "
                "across them is labelled UNSTABLE and must not be read as "
                "advice. Varying only the estimator seed would not have caught "
                "this — the flip that prompted the check came from a fold "
                "change."
            ),
        },
        "not_causal": NOT_CAUSAL,
        "note": (
            "Only features a seller or builder could plausibly change are "
            "shown. Location features move price far more, but nobody can act "
            "on them — they are in the SHAP importance chart instead."
        ),
    }

    # ------------------------------------------------ plot
    if curves:
        n = len(curves)
        fig, axes = plt.subplots(1, n, figsize=(3.4 * n, 3.2), squeeze=False)
        for ax, c in zip(axes[0], curves, strict=True):
            ax.plot(c["grid"], c["predicted"], marker="o", lw=2, color="#1E3A8A")
            ax.set_title(c["feature"] + ("" if c["stable_across_seeds"]
                                          else "  (UNSTABLE)"),
                         fontsize=10,
                         color="#1E3A8A" if c["stable_across_seeds"] else "#B91C1C")
            ax.set_xlabel(c["feature"], fontsize=8)
            ax.set_ylabel("predicted ₹/sq.ft", fontsize=8)
            ax.tick_params(labelsize=7)
            ax.grid(alpha=0.3)
        fig.suptitle(f"{cfg.display} — what moves the model's price "
                     "(partial dependence, NOT causal)", fontsize=11)
        fig.tight_layout()
        fig.savefig(art / "partial_dependence.png", dpi=130)
        plt.close(fig)
        print(f"\n  wrote {art / 'partial_dependence.png'}")

    # Persist the fitted quantile models plus the conformal offset, so the band
    # can be computed for one property at request time rather than only
    # reported as an aggregate. qhat travels with them: a band served without
    # its conformal adjustment would be the uncalibrated one.
    bundle = {
        "models": fitted,
        "qhat": qhat,
        "quantiles": list(QUANTILES),
        "feature_columns": {"numeric": numeric, "categorical": categorical},
        "target": cfg.target,
        "conformalized_coverage": conf_cov,
        "calibrated": bool(conf_ok and not few_blocks),
        "trained_at": datetime.now(UTC).isoformat(),
    }
    joblib.dump(bundle, models_dir / "quantile_band.joblib")
    print(f"  wrote {models_dir / 'quantile_band.joblib'}")

    (art / "advisory_models.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  wrote {art / 'advisory_models.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
