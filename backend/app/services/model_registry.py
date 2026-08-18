"""Every model this project has actually trained, read off disk.

The ML work is spread across five tabs — price, performance, extra models,
future price, negotiation band. That is fine for using the app and useless for
answering the one question a reviewer asks first: *what did you actually train,
and does any of it work?*

So this enumerates the trained artefacts themselves. Two rules make it worth
trusting:

  * **It lists what is on disk, not what the code intends.** Each entry is
    anchored to a `.joblib` file whose size and modification time are read
    live. A model that was never trained does not appear; a model whose script
    exists but never ran shows as absent.

  * **Every entry carries a verdict, and the verdict can be negative.** Four of
    the models here are not usable as advertised — a degenerate classifier, an
    uncalibrated band, an over-conservative band, a refused forecast. A
    registry that showed only green ticks would be worse than no registry.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "models"
ARTIFACTS = ROOT / "ml" / "artifacts"

# Verdicts. WORKS is not the default — it has to be earned by a measured number.
WORKS = "WORKS"
LIMITED = "WORKS WITH LIMITS"
NOT_USABLE = "TRAINED BUT NOT USABLE"
ABSENT = "NOT TRAINED"


def _artifact(city: str, name: str) -> dict[str, Any]:
    path = ARTIFACTS / city / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _file(city: str, filename: str) -> dict[str, Any] | None:
    path = MODELS / city / filename
    if not path.exists():
        return None
    st = path.stat()
    return {
        "file": f"models/{city}/{filename}",
        "size_kb": round(st.st_size / 1024),
        "trained_at": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(),
    }


def _entry(*, family: str, name: str, task: str, algorithm: str,
           file_info: dict[str, Any] | None, verdict: str, headline: str,
           metrics: dict[str, Any], validation: str,
           caveat: str | None = None) -> dict[str, Any]:
    return {
        "family": family,
        "name": name,
        "task": task,
        "algorithm": algorithm,
        "trained": file_info is not None,
        "artefact": file_info,
        "verdict": verdict if file_info else ABSENT,
        "headline": headline if file_info else "Not trained — run its pipeline.",
        "metrics": metrics,
        "validation": validation,
        "caveat": caveat,
    }


def _regression(city: str) -> list[dict[str, Any]]:
    m = _artifact(city, "metrics.json")
    if not m:
        return []
    comparison = m.get("model_comparison", {}) or {}
    shipped = comparison.get(m.get("algorithm"), {}) or {}
    spatial = (shipped.get("spatial_cv", {}) or {}).get("r2")
    if spatial is None:
        spatial = m.get("honest_generalisation_r2")
    random_cv = (shipped.get("random_cv", {}) or {}).get("r2")
    leakage = shipped.get("leakage_gap_r2")
    interval = m.get("conformal", {}) or {}
    test = m.get("final_test_metrics", {}) or {}

    out = [_entry(
        family="Regression",
        name="Price model (shipped)",
        task=f"Predict {m.get('target_label', 'price per sq.ft')}",
        algorithm=m.get("algorithm") or m.get("model", "unknown"),
        file_info=_file(city, "price_model.joblib"),
        verdict=(WORKS if (spatial or 0) > 0.3 else LIMITED),
        headline=(f"Spatial-CV R² {spatial} — selected on this, not on the "
                  f"random-CV {random_cv}"),
        metrics={
            "spatial_cv_r2": spatial,
            "random_cv_r2": random_cv,
            "leakage_gap_r2": leakage,
            "test_r2": test.get("r2"),
            "test_mae": test.get("mae"),
            "test_mape": test.get("mape_pct"),
            "interval_nominal": interval.get("nominal_coverage",
                                             interval.get("nominal")),
            "interval_measured_coverage": interval.get(
                "empirical_coverage", interval.get("measured_coverage")),
        },
        validation="GroupKFold by spatial block; split conformal interval",
        caveat=m.get("test_split_warning"),
    )]

    # Candidate algorithms are kept, so say so rather than implying one model.
    for algo in ("linear_regression", "random_forest", "gradient_boosting",
                 "hist_gradient_boosting", "xgboost"):
        info = _file(city, f"model_{algo}.joblib")
        if not info:
            continue
        comp = comparison.get(algo, {}) or {}
        r2 = (comp.get("spatial_cv", {}) or {}).get("r2")
        out.append(_entry(
            family="Regression",
            name=f"Candidate — {algo}",
            task="Same target; retained for the ensemble and for comparison",
            algorithm=algo,
            file_info=info,
            verdict=LIMITED,
            headline=(f"Spatial-CV R² {r2}" if r2 is not None
                      else "Retained candidate"),
            metrics={"spatial_cv_r2": r2,
                     "random_cv_r2": (comp.get("random_cv", {}) or {}).get("r2"),
                     "leakage_gap_r2": comp.get("leakage_gap_r2")},
            validation="GroupKFold by spatial block",
            caveat=("A candidate, not the shipped model. Used by the dual and "
                    "multi-model prediction strategies."),
        ))
    return out


def _extra(city: str) -> list[dict[str, Any]]:
    d = _artifact(city, "extra_models.json")
    if not d:
        return []
    out = []

    cl = d.get("classification", {})
    if cl:
        degenerate = bool(cl.get("warning"))
        out.append(_entry(
            family="Classification",
            name="Price-band classifier",
            task="Budget / Mid-market / Premium from the same features",
            algorithm="RandomForestClassifier",
            file_info=_file(city, "price_band_classifier.joblib"),
            verdict=NOT_USABLE if degenerate else WORKS,
            headline=(cl["warning"][:120] if degenerate else
                      f"Accuracy {cl.get('accuracy')} against a "
                      f"{cl.get('chance_accuracy')} chance line, macro F1 "
                      f"{cl.get('macro_f1')}"),
            metrics={
                "accuracy": cl.get("accuracy"),
                "chance_accuracy": cl.get("chance_accuracy"),
                "macro_f1": cl.get("macro_f1"),
                "roc_auc_ovr_macro": cl.get("roc_auc_ovr_macro"),
                "classes_never_predicted": cl.get("classes_never_predicted"),
            },
            validation=cl.get("split", ""),
            caveat=cl.get("warning") or cl.get("label_note"),
        ))

    cu = d.get("clustering", {})
    info = _file(city, "locality_clusters.joblib")
    if cu.get("available") or info:
        out.append(_entry(
            family="Clustering",
            name="Locality segmentation",
            task="Group localities by price and amenity profile (unsupervised)",
            algorithm="KMeans",
            file_info=info,
            verdict=WORKS if cu.get("available") else NOT_USABLE,
            headline=(f"k={cu.get('k')} chosen by silhouette "
                      f"{cu.get('silhouette')}, {cu.get('localities_clustered')} "
                      "localities" if cu.get("available")
                      else cu.get("reason", "Refused — too few localities")),
            metrics={"k": cu.get("k"), "silhouette": cu.get("silhouette"),
                     "localities": cu.get("localities_clustered")},
            validation=cu.get("k_selection", "silhouette score"),
            caveat=None if cu.get("available") else cu.get("reason"),
        ))

    an = d.get("anomaly", {})
    if an:
        out.append(_entry(
            family="Anomaly detection",
            name="Atypical record detector",
            task="Flag records unusual across their whole feature vector",
            algorithm="IsolationForest",
            file_info=_file(city, "anomaly_detector.joblib"),
            verdict=LIMITED,
            headline=f"{an.get('flagged'):,} of {an.get('total'):,} flagged",
            metrics={"flagged": an.get("flagged"), "total": an.get("total"),
                     "features": len(an.get("features", []))},
            validation="Unsupervised — no ground-truth anomaly label exists",
            caveat=an.get("caveat"),
        ))
    return out


def _advisory(city: str) -> list[dict[str, Any]]:
    d = _artifact(city, "advisory_models.json")
    if not d:
        return []
    band = d.get("negotiation_band", {})
    conf = band.get("conformalized", {})
    reliable = bool(conf.get("reliable"))
    return [_entry(
        family="Quantile regression",
        name="Negotiation band (P10/P50/P90)",
        task="Defensible offer, realistic midpoint, ambitious ask",
        algorithm="GradientBoostingRegressor (pinball loss) + conformal (CQR)",
        file_info=_file(city, "quantile_band.joblib"),
        verdict=WORKS if reliable else NOT_USABLE,
        headline=(f"Coverage {conf.get('measured_coverage', 0):.1%} against an "
                  f"80% target ({conf.get('direction')})"),
        metrics={
            "target_coverage": conf.get("target_coverage"),
            "measured_coverage": conf.get("measured_coverage"),
            "direction": conf.get("direction"),
            "random_split_coverage": (conf.get("exchangeability_check", {})
                                      .get("random_split_coverage")),
            "pinball_loss": band.get("pinball_loss"),
            "quantile_crossing_rate": (band.get("quantile_crossing", {})
                                       .get("rate")),
        },
        validation=d.get("split", ""),
        caveat=(conf.get("few_blocks_warning")
                or (None if reliable else
                    "Coverage is off target — the band must not be quoted as "
                    "an 80% band.")),
    )]


def _future(city: str) -> list[dict[str, Any]]:
    """Bengaluru's forecast is REFUSED, not missing — a different thing.

    The pipeline ran, examined the dataset, found it records possession timing
    rather than sale dates, and declined to forecast. Reporting that as "not
    trained" would hide a deliberate decision behind an apparent gap.
    """
    d = _artifact(city, "future_price.json")
    if not d:
        return []

    supported = bool(d.get("available"))
    # Not every artefact records its own timestamp, so fall back to the file's
    # mtime — which is always present and is the honest "when was this made".
    art_path = ARTIFACTS / city / "future_price.json"
    ran = {
        "file": f"ml/artifacts/{city}/future_price.json",
        "size_kb": round(art_path.stat().st_size / 1024),
        "trained_at": (d.get("checked_at") or d.get("generated_at")
                       or datetime.fromtimestamp(art_path.stat().st_mtime,
                                                 UTC).isoformat()),
    }

    # A forecast that does not beat a naive baseline is not a working
    # forecast, however plausible its CAGR looks.
    beats = d.get("beats_naive_baseline")
    if supported:
        headline = (f"CAGR {d.get('cagr_pct')}% — "
                    + ("beats the naive baseline on a time-based split"
                       if beats else
                       "DOES NOT BEAT a naive baseline, so the trend carries no "
                       "predictive value over simply carrying the last value "
                       "forward"))
        metrics = {k: d.get(k) for k in
                   ("cagr_pct", "beats_naive_baseline", "forecast_from_year",
                    "forecast_from_value") if d.get(k) is not None}
        caveat = d.get("critical_caveat") or d.get("baseline_note")
    else:
        headline = ("REFUSED — " + str(d.get("reason", ""))[:150])
        metrics = {"temporal_basis": d.get("temporal_basis"),
                   "forecast_supported": d.get("forecast_supported")}
        caveat = (str(d.get("why_this_matters") or "")
                  + " " + str(d.get("what_would_be_needed") or "")).strip() or None

    return [_entry(
        family="Temporal",
        name="Future price",
        task="Project price forward from dated transactions",
        algorithm=d.get("method", "time-indexed trend + naive baseline"),
        file_info=ran,
        verdict=(WORKS if (supported and beats) else NOT_USABLE),
        headline=headline,
        metrics=metrics,
        validation=("Time-based split — train on past, test on future"
                    if supported else
                    "Not applicable — the pipeline declined to forecast"),
        caveat=caveat,
    )]


@lru_cache(maxsize=4)
def registry(city: str) -> dict[str, Any]:
    entries = (_regression(city) + _extra(city) + _advisory(city)
               + _future(city))

    counts: dict[str, int] = {}
    for e in entries:
        counts[e["verdict"]] = counts.get(e["verdict"], 0) + 1

    families = sorted({e["family"] for e in entries})
    trained = [e for e in entries if e["trained"]]
    total_kb = sum((e["artefact"] or {}).get("size_kb", 0) for e in trained)

    return {
        "city": city,
        "models": entries,
        "count": len(entries),
        "trained_count": len(trained),
        "families": families,
        "verdicts": counts,
        "total_artefact_kb": total_kb,
        "how_to_read": (
            "Every row is anchored to a file on disk — size and training time "
            "are read live, so a model that was never trained cannot appear "
            "here. WORKS is earned by a measured number, not assumed."
        ),
        "why_negatives_are_shown": (
            f"{counts.get(NOT_USABLE, 0)} of {len(entries)} models are trained "
            "but not usable as advertised. They are listed because a registry "
            "showing only successes would misrepresent the project — and "
            "because knowing which model not to trust is the useful part."
        ),
    }
