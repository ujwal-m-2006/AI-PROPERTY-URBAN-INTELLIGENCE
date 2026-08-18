"""Module 15 — future price prediction.

Only attempted where the data actually supports it.

    Chennai    DATE_SALE spans 2004-2015, so a time-aware model can be trained
               and validated on held-out FUTURE years.
    Bengaluru  the listing dataset carries no sale dates at all. No temporal
               model is trained, and the API reports insufficient history rather
               than inventing a trend.

Three deliberate choices:

1. **Time-based validation, never random.** Training on later years to predict
   earlier ones would leak the future into the past and produce a meaningless
   score. Train is the early years; validation is the last three.

2. **A naive baseline is mandatory.** "Next year equals this year" is
   surprisingly hard to beat on short annual series. A model that cannot beat it
   has demonstrated nothing, and the report says so explicitly.

3. **Forecasts run from the END OF THE DATA, not from today.** The series stops
   in 2015. Projecting to the present would be an 11-year extrapolation from a
   12-point annual series — indefensible, and refused here.

    python ml/pipelines/train_future_price.py chennai
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
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor  # noqa: E402
from sklearn.linear_model import LinearRegression  # noqa: E402
from sklearn.metrics import mean_absolute_error  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipelines import city_config  # noqa: E402

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
RANDOM_STATE = 42
VALIDATION_YEARS = 3
HORIZONS = (1, 3, 5)

NAVY, ACCENT, GREY = "#1B365D", "#C2703A", "#8A94A3"


def build_panel(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """Locality-year panel of median price per sq.ft."""
    d = df.dropna(subset=["sale_year"]).copy()
    d["sale_year"] = d["sale_year"].astype(int)
    panel = (
        d.groupby([cfg.locality_column, "sale_year"])["price_per_sqft"]
        .agg(["median", "count"])
        .reset_index()
        .rename(columns={"median": "psf", cfg.locality_column: "locality",
                         "sale_year": "year"})
    )
    # A median over very few sales is noise, not a market level.
    return panel[panel["count"] >= 5].sort_values(["locality", "year"])


def add_lags(panel: pd.DataFrame) -> pd.DataFrame:
    """Temporal features. Every one uses only information available at time t."""
    out = panel.copy()
    g = out.groupby("locality")["psf"]
    out["lag1"] = g.shift(1)
    out["lag2"] = g.shift(2)
    out["roll3"] = g.shift(1).rolling(3, min_periods=1).mean().reset_index(0, drop=True)
    out["yoy"] = (out["lag1"] - out["lag2"]) / out["lag2"]
    out["years_since_start"] = out["year"] - out["year"].min()
    return out.dropna(subset=["lag1"])



def possession_analysis(city: str, cfg, art: Path) -> int:
    """Bengaluru path — the only time signal is POSSESSION year, not sale year.

    Every price in this dataset was observed at a single scrape. Variation
    across possession years therefore measures the discount buyers demand for
    an unfinished property, NOT how the market moved over time. A market
    forecast is refused here; the possession-premium relationship is real and is
    modelled and reported instead.
    """
    df, _ = cfg.clean(city_config.load_raw(cfg))
    ready = df[df["ready_to_move"] == 1]["price_per_sqft"]
    under = df[df["possession_year"].notna()]

    by_year = (under.groupby(under["possession_year"].astype(int))["price_per_sqft"]
               .agg(["median", "count"]).reset_index()
               .rename(columns={"possession_year": "year", "median": "psf"}))
    by_year = by_year[by_year["count"] >= 20]

    print("  temporal basis: POSSESSION year (not sale date)")
    print(f"  ready-to-move: {len(ready):,} rows, median Rs {ready.median():,.0f}/sq.ft")
    print(f"  under-construction with a possession year: {len(under):,} rows")
    print(f"\n  {'possession year':<18}{'median psf':>12}{'listings':>10}")
    for r in by_year.itertuples():
        print(f"  {int(r.year):<18}{r.psf:>12,.0f}{int(r.count):>10}")

    premium = None
    slope = None
    if len(by_year) >= 3:
        X = by_year[["year"]].to_numpy()
        y = by_year["psf"].to_numpy()
        lr = LinearRegression().fit(X, y)
        slope = float(lr.coef_[0])
        r2 = float(lr.score(X, y))
        med_ready = float(ready.median())
        med_under = float(under["price_per_sqft"].median())
        premium = round((med_ready - med_under) / med_under * 100, 1)
        print(f"\n  ready-to-move premium over under-construction: {premium:+.1f}%")
        print(f"  slope across possession years: Rs {slope:,.0f}/sq.ft per year "
              f"(R2 {r2:.3f})")

    payload = {
        "city": city,
        "available": False,
        "forecast_supported": False,
        "temporal_basis": cfg.temporal_basis,
        "reason": (
            f"The {cfg.display} dataset records POSSESSION timing, not sale dates. "
            "Every price was observed at a single point in time, so no price "
            "series over time exists and no market forecast can be produced from "
            "this data."
        ),
        "why_this_matters": (
            "A trend across possession years would measure the discount on "
            "unfinished property, not market appreciation. Presenting it as a "
            "price forecast would be wrong."
        ),
        "what_would_be_needed": [
            "Sale or listing dates on each record (as the Chennai dataset has), or",
            "A published locality-level price index over several years, or",
            "Repeated scrapes of the same listings over time",
        ],
        "supported_analysis": {
            "name": "Possession-timing premium",
            "method": "Median price per sq.ft by possession year, plus a linear fit",
            "ready_to_move_rows": int(len(ready)),
            "ready_to_move_median_psf": round(float(ready.median())),
            "under_construction_rows": int(len(under)),
            "under_construction_median_psf": round(float(under["price_per_sqft"].median())),
            "ready_premium_pct": premium,
            "slope_per_possession_year": round(slope, 1) if slope is not None else None,
            "by_possession_year": [
                {"year": int(r.year), "median_psf": round(float(r.psf)),
                 "listings": int(r.count)} for r in by_year.itertuples()
            ],
            "interpretation": (
                "Ready-to-move properties are listed at a premium over "
                "under-construction ones. This is a possession-timing effect, "
                "NOT a market trend over time."
            ),
        },
        "checked_at": datetime.now(UTC).isoformat(),
    }

    if len(by_year) >= 3:
        plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white",
                             "axes.grid": True, "grid.color": "#E6EAF0"})
        fig, ax = plt.subplots(figsize=(7.2, 4.0))
        ax.bar(by_year["year"].astype(int), by_year["psf"], color=NAVY, width=0.6,
               label="Under construction (by possession year)")
        ax.axhline(float(ready.median()), color=ACCENT, linewidth=2, linestyle="--",
                   label=f"Ready to move — median Rs {ready.median():,.0f}")
        ax.set_xlabel("Possession year (NOT sale year)")
        ax.set_ylabel("Median price per sq.ft (INR)")
        ax.set_title("Greater Bengaluru — possession timing, not a market trend",
                     color=NAVY, fontweight="bold")
        ax.legend(frameon=False, fontsize=9)
        fig.tight_layout(); fig.savefig(art / "future_price.png", dpi=140); plt.close(fig)
        payload["plot"] = "future_price.png"

    (art / "future_price.json").write_text(json.dumps(payload, indent=2),
                                           encoding="utf-8")
    print(f"\n  FORECAST NOT SUPPORTED for {cfg.display} - reported with the reason.")
    print(f"  wrote {art / 'future_price.json'}")
    return 0


def main() -> int:
    city = (sys.argv[1] if len(sys.argv) > 1 else "chennai").strip().lower()
    cfg = city_config.get(city)
    art = ROOT / "ml" / "artifacts" / city
    art.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}\n  {cfg.display.upper()} — FUTURE PRICE PREDICTION\n{'=' * 70}")

    if not cfg.supports_temporal:
        return possession_analysis(city, cfg, art)

    df, _ = cfg.clean(city_config.load_raw(cfg))
    panel = build_panel(df, cfg)
    years = sorted(panel["year"].unique())
    print(f"  panel: {len(panel)} locality-year points, "
          f"{panel['locality'].nunique()} localities, {years[0]}-{years[-1]}")

    feat = add_lags(panel)
    split_year = years[-VALIDATION_YEARS]
    train = feat[feat["year"] < split_year]
    valid = feat[feat["year"] >= split_year]
    print(f"  time split: train {years[0]}-{split_year - 1} ({len(train)} rows) | "
          f"validate {split_year}-{years[-1]} ({len(valid)} rows)")

    if len(train) < 20 or len(valid) < 5:
        payload = {
            "city": city, "available": False,
            "reason": (
                f"Only {len(train)} training and {len(valid)} validation points "
                "remain after aggregation. This is too little history for a "
                "reliable temporal model."
            ),
            "checked_at": datetime.now(UTC).isoformat(),
        }
        (art / "future_price.json").write_text(json.dumps(payload, indent=2),
                                               encoding="utf-8")
        print(f"  INSUFFICIENT DATA — {payload['reason']}")
        return 0

    FEATURES = ["lag1", "lag2", "roll3", "yoy", "years_since_start"]
    Xtr, ytr = train[FEATURES].fillna(0), train["psf"]
    Xva, yva = valid[FEATURES].fillna(0), valid["psf"]

    # The bar every model must clear.
    naive_pred = valid["lag1"].to_numpy()
    naive_mae = mean_absolute_error(yva, naive_pred)
    naive_mape = float(np.mean(np.abs((yva - naive_pred) / yva)) * 100)

    models = {
        "linear_regression": LinearRegression(),
        "random_forest": RandomForestRegressor(
            n_estimators=300, min_samples_leaf=2, random_state=RANDOM_STATE, n_jobs=-1),
        "gradient_boosting": GradientBoostingRegressor(random_state=RANDOM_STATE),
    }

    print(f"\n  {'model':<24}{'MAE':>10}{'MAPE %':>10}   vs naive")
    print("  " + "-" * 58)
    print(f"  {'naive (carry forward)':<24}{naive_mae:>10,.0f}{naive_mape:>10.2f}   baseline")

    results: dict[str, Any] = {
        "naive_carry_forward": {"mae": round(naive_mae, 1),
                                "mape_pct": round(naive_mape, 2)}
    }
    best_name, best_mae, best_model = None, float("inf"), None
    for name, est in models.items():
        est.fit(Xtr, ytr)
        pred = est.predict(Xva)
        mae = mean_absolute_error(yva, pred)
        mape = float(np.mean(np.abs((yva - pred) / yva)) * 100)
        beats = mae < naive_mae
        results[name] = {"mae": round(mae, 1), "mape_pct": round(mape, 2),
                         "beats_naive": bool(beats)}
        print(f"  {name:<24}{mae:>10,.0f}{mape:>10.2f}   "
              f"{'BEATS naive' if beats else 'does NOT beat naive'}")
        if mae < best_mae:
            best_name, best_mae, best_model = name, mae, est

    beat_naive = best_mae < naive_mae
    print(f"\n  best: {best_name} (MAE {best_mae:,.0f})")
    if not beat_naive:
        print("  !! No model beats carrying the previous year forward. On a series "
              "this short that is a real and reportable outcome.")

    # --- city-level index and forecast ----------------------------------
    city_year = (panel.groupby("year")
                 .apply(lambda g: np.average(g["psf"], weights=g["count"]))
                 .rename("psf").reset_index())
    yrs = city_year["year"].to_numpy().reshape(-1, 1)
    vals = city_year["psf"].to_numpy()

    trend = LinearRegression().fit(yrs, vals)
    slope = float(trend.coef_[0])
    last_year, last_value = int(city_year["year"].iloc[-1]), float(vals[-1])
    cagr = ((vals[-1] / vals[0]) ** (1 / (len(vals) - 1)) - 1) * 100 if len(vals) > 1 else 0.0

    # The projection deliberately uses trend and CAGR rather than the fitted
    # model. `best_model` is only trusted to forecast if it actually beat the
    # naive baseline on held-out years; otherwise using it would add error
    # without evidence of benefit. This keeps the reported "selected_model"
    # honest about the part it plays.
    forecast_basis = (
        f"{best_name} (beat the naive baseline on held-out years)"
        if beat_naive else
        "linear trend and CAGR on the city index — no model beat the naive "
        "baseline, so none is trusted to extrapolate"
    )

    forecasts = []
    for h in HORIZONS:
        target_year = last_year + h
        linear_v = float(trend.predict([[target_year]])[0])
        cagr_v = last_value * ((1 + cagr / 100) ** h)
        entry = {
            "horizon_years": h,
            "target_year": target_year,
            "linear_trend": round(linear_v),
            "cagr_projection": round(cagr_v),
            "range_low": round(min(linear_v, cagr_v)),
            "range_high": round(max(linear_v, cagr_v)),
        }
        if beat_naive and best_model is not None:
            # Recursive one-step-ahead roll forward from the last observation.
            psf, lag1, lag2 = last_value, last_value, float(vals[-2]) if len(vals) > 1 else last_value
            for step in range(h):
                row = [[lag1, lag2, (lag1 + lag2) / 2,
                        (lag1 - lag2) / lag2 if lag2 else 0.0,
                        (last_year - int(city_year["year"].iloc[0])) + step + 1]]
                psf = float(best_model.predict(row)[0])
                lag2, lag1 = lag1, psf
            entry["model_projection"] = round(psf)
        forecasts.append(entry)

    print(f"\n  city index {years[0]}-{years[-1]}: "
          f"Rs {vals[0]:,.0f} -> Rs {vals[-1]:,.0f}/sq.ft (CAGR {cagr:.2f}%)")
    print(f"  {'horizon':<12}{'year':>6}{'linear':>12}{'CAGR':>12}")
    for f in forecasts:
        print(f"  {str(f['horizon_years']) + ' yr':<12}{f['target_year']:>6}"
              f"{f['linear_trend']:>12,}{f['cagr_projection']:>12,}")

    # --- plot ------------------------------------------------------------
    plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white",
                         "axes.grid": True, "grid.color": "#E6EAF0"})
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.plot(city_year["year"], vals, "o-", color=NAVY, linewidth=2,
            label="Observed (volume-weighted median)")
    fy = [f["target_year"] for f in forecasts]
    ax.plot([last_year] + fy, [last_value] + [f["linear_trend"] for f in forecasts],
            "s--", color=ACCENT, linewidth=1.8, label="Linear trend projection")
    ax.plot([last_year] + fy, [last_value] + [f["cagr_projection"] for f in forecasts],
            "^:", color=GREY, linewidth=1.8, label="CAGR projection")
    ax.axvline(last_year, color=GREY, linestyle=":", linewidth=1)
    ax.text(last_year, ax.get_ylim()[0], " end of data", fontsize=8, color=GREY)
    ax.set_xlabel("Year"); ax.set_ylabel("Price per sq.ft (INR)")
    ax.set_title(f"{cfg.display} — price index and projection", color=NAVY,
                 fontweight="bold")
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(art / "future_price.png", dpi=140); plt.close(fig)

    payload = {
        "city": city,
        "available": True,
        "method": "Time-aware regression on a locality-year panel",
        "panel": {
            "rows": int(len(panel)),
            "localities": int(panel["locality"].nunique()),
            "year_min": int(years[0]), "year_max": int(years[-1]),
            "min_sales_per_point": 5,
        },
        "validation": {
            "scheme": "time-based — train on earlier years, validate on the last "
                      f"{VALIDATION_YEARS}",
            "train_years": f"{years[0]}-{split_year - 1}",
            "validation_years": f"{split_year}-{years[-1]}",
            "train_rows": int(len(train)), "validation_rows": int(len(valid)),
            "note": "Random splitting is not used: it would leak future values "
                    "into the training set.",
        },
        "results": results,
        "selected_model": best_name,
        "beats_naive_baseline": bool(beat_naive),
        "baseline_note": (
            "The naive baseline carries the previous year's value forward. "
            + ("The selected model beats it."
               if beat_naive else
               "No model beats it — on a series this short, that is the honest "
               "result and is reported rather than hidden.")
        ),
        "city_index": [
            {"year": int(r.year), "psf": round(float(r.psf))}
            for r in city_year.itertuples()
        ],
        "cagr_pct": round(cagr, 2),
        "trend_slope_per_year": round(slope, 1),
        "forecast_basis": forecast_basis,
        "forecast_from_year": last_year,
        "forecast_from_value": round(last_value),
        "forecasts": forecasts,
        "critical_caveat": (
            f"Projections run forward from {last_year}, the last year in the "
            f"data — NOT from the present day. The series ends in {last_year}, so "
            "these are not forecasts of today's market and must not be read as "
            "current or future prices."
        ),
        "plot": "future_price.png",
        "trained_at": datetime.now(UTC).isoformat(),
    }
    (art / "future_price.json").write_text(json.dumps(payload, indent=2),
                                           encoding="utf-8")
    print(f"\n  wrote {art / 'future_price.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
