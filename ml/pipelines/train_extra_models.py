"""Additional ML models — classification, clustering and anomaly detection.

The project is otherwise entirely regression. These three add the model families
an ML review expects to see, and each answers a question the site actually needs.

1. PRICE-BAND CLASSIFICATION  (supervised, multi-class)
   "Is this budget, mid-market or premium?"
   Bands are cut at the dataset's own price-per-sq.ft terciles, so the label is
   derived from data rather than invented. Reports accuracy, precision, recall,
   F1, a confusion matrix and one-vs-rest ROC-AUC — evaluated under the same
   spatial-block split as the regression, so the scores are comparable.

   NOTE ON THE LABEL: the band is derived from the target, so this is a
   discretised view of the same problem, not new information. It is useful for
   presentation and for coarse filtering; it is not independent evidence.

2. LOCALITY CLUSTERING  (unsupervised, KMeans)
   "Which localities behave like this one?"
   Clusters localities on price level, price spread, size and configuration mix.
   k is chosen by silhouette score rather than assumed.

3. OVERPRICING DETECTION  (unsupervised, Isolation Forest)
   "Is this listing unusual for its own locality?"
   Complements the existing interval-based check: the interval asks whether a
   price is far from the model, this asks whether the whole record is atypical.

    python ml/pipelines/train_extra_models.py bengaluru
    python ml/pipelines/train_extra_models.py chennai
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
from sklearn.cluster import DBSCAN, KMeans  # noqa: E402
from sklearn.ensemble import IsolationForest, RandomForestClassifier  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    calinski_harabasz_score,
    classification_report,
    confusion_matrix,
    davies_bouldin_score,
    roc_auc_score,
    silhouette_score,
)
from sklearn.model_selection import GroupShuffleSplit  # noqa: E402
from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.gis_features import add_gis_features  # noqa: E402
from pipelines import city_config  # noqa: E402
from pipelines.train_city_model import GIS_NUMERIC, build_pipeline  # noqa: E402

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
CONTAMINATION = 0.05
DBSCAN_MIN_SAMPLES = 5
RANDOM_STATE = 42
NAVY, ACCENT = "#1B365D", "#C2703A"
BANDS = ["Budget", "Mid-market", "Premium"]


def cluster_validity(Z, labels) -> dict[str, float]:
    """Three indices, because one is a choice and three are a check.

    They disagree by construction: silhouette rewards separation per point,
    Davies-Bouldin penalises overlapping cluster spreads, Calinski-Harabasz is
    a variance ratio that rises with k almost by default. Agreement between
    them is evidence the structure is real; disagreement means the "best" k was
    a property of the index.
    """
    return {
        "silhouette": round(float(silhouette_score(Z, labels)), 4),
        "davies_bouldin": round(float(davies_bouldin_score(Z, labels)), 4),
        "calinski_harabasz": round(float(calinski_harabasz_score(Z, labels)), 1),
    }


def _dbscan_eps(A, min_samples: int, target_rate: float) -> float:
    """eps that flags about `target_rate` of points as noise.

    DBSCAN has no contamination parameter, so comparing it against detectors
    that do would otherwise compare flag rates rather than flag agreement.
    Calibrating eps to the same budget makes the comparison about *which* rows.
    """
    nn = NearestNeighbors(n_neighbors=min_samples).fit(A)
    d, _ = nn.kneighbors(A)
    return float(np.quantile(d[:, -1], 1.0 - target_rate))


def detector_agreement(flags: dict[str, np.ndarray]) -> dict[str, Any]:
    """How much do the detectors agree about which rows are anomalous?

    Each array is a boolean mask over the same rows. Jaccard is the honest
    measure here: all three flag ~5% of records, so raw agreement would be ~90%
    on the rows nobody flagged.
    """
    names = sorted(flags)
    pairs = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            inter = int((flags[a] & flags[b]).sum())
            union = int((flags[a] | flags[b]).sum())
            pairs[f"{a} vs {b}"] = {
                "jaccard": round(inter / union, 4) if union else 0.0,
                "both": inter,
            }
    stack = np.vstack([flags[n] for n in names])
    all_three = int(stack.all(axis=0).sum())
    any_one = int(stack.any(axis=0).sum())
    return {
        "pairwise": pairs,
        "flagged_by_all": all_three,
        "flagged_by_any": any_one,
        "unanimous_share_of_any": round(all_three / any_one, 4) if any_one else 0.0,
    }


def main() -> int:
    city = (sys.argv[1] if len(sys.argv) > 1 else "bengaluru").strip().lower()
    cfg = city_config.get(city)
    art = ROOT / "ml" / "artifacts" / city
    models_dir = ROOT / "models" / city
    art.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 72}\n  {cfg.display.upper()} — CLASSIFICATION, CLUSTERING, ANOMALY\n{'=' * 72}")

    df, _ = cfg.clean(city_config.load_raw(cfg))
    df, gis = add_gis_features(
        df, locality_column=cfg.locality_column, city=city,
        amenities_file=cfg.amenities_file, wards_file=cfg.wards_file)
    df["has_gis"] = df["gis_lat"].notna().astype(int)
    print(f"  {len(df):,} rows | locality match {gis['locality_match_rate']:.1%}")

    numeric = [c for c in cfg.numeric_features if c in df.columns]
    numeric += [c for c in GIS_NUMERIC if c in df.columns] + ["has_gis"]
    categorical = [c for c in cfg.categorical_features if c in df.columns]
    if df.get("gis_corporation") is not None and df["gis_corporation"].notna().any():
        categorical = categorical + ["gis_corporation"]

    groups = df["gis_ward_no"].astype("object").where(
        df["gis_ward_no"].notna(), "loc:" + df[cfg.locality_column].astype(str)
    ).astype(str)

    payload: dict[str, Any] = {
        "city": city, "display": cfg.display,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    # ---------------------------------------------- 1. classification
    print("\n[1] PRICE-BAND CLASSIFICATION")
    q1, q2 = df[cfg.target].quantile([1 / 3, 2 / 3])
    y = pd.cut(df[cfg.target], bins=[-np.inf, q1, q2, np.inf], labels=BANDS)
    X = df[numeric + categorical]
    print(f"    bands cut at the data's own terciles: "
          f"<= {q1:,.0f} | <= {q2:,.0f} | above")
    print(f"    class balance: {dict(y.value_counts())}")

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25,
                                 random_state=RANDOM_STATE)
    tr, te = next(splitter.split(X, y, groups))
    clf = build_pipeline(
        RandomForestClassifier(n_estimators=300, min_samples_leaf=2,
                               random_state=RANDOM_STATE, n_jobs=-1),
        numeric, categorical)
    clf.fit(X.iloc[tr], y.iloc[tr])
    pred = clf.predict(X.iloc[te])
    proba = clf.predict_proba(X.iloc[te])

    rep = classification_report(y.iloc[te], pred, output_dict=True, zero_division=0)
    cm = confusion_matrix(y.iloc[te], pred, labels=BANDS)
    try:
        auc = float(roc_auc_score(y.iloc[te], proba, multi_class="ovr",
                                  average="macro"))
    except ValueError:
        auc = None

    print(f"    split: grouped by locality/ward — train {len(tr):,}, test {len(te):,}")
    print(f"    accuracy {rep['accuracy']:.4f} | macro F1 {rep['macro avg']['f1-score']:.4f}"
          + (f" | ROC-AUC (ovr) {auc:.4f}" if auc else ""))
    for b in BANDS:
        r = rep.get(b, {})
        print(f"      {b:<12} precision {r.get('precision', 0):.3f}  "
              f"recall {r.get('recall', 0):.3f}  f1 {r.get('f1-score', 0):.3f}  "
              f"n={int(r.get('support', 0))}")
    print("    confusion matrix (rows = actual, cols = predicted):")
    print("      " + "".join(f"{b[:9]:>11}" for b in BANDS))
    for i, b in enumerate(BANDS):
        print(f"      {b[:9]:<9}" + "".join(f"{int(v):>11}" for v in cm[i]))

    # A classifier that predicts one class for everything is not a working
    # model, however its accuracy reads. With few localities a grouped split can
    # leave the model no way to place an unseen area, and it collapses to the
    # majority class. Detect that and say so.
    predicted_classes = set(pd.Series(pred).unique())
    zero_recall = [b for b in BANDS if rep.get(b, {}).get("recall", 0) == 0]
    n_classes = len(BANDS)
    chance = 1.0 / n_classes
    degenerate = bool(zero_recall) or len(predicted_classes) < n_classes
    barely_better = rep["accuracy"] < chance * 1.25

    warning = None
    if degenerate:
        warning = (
            f"DEGENERATE MODEL — the classifier never predicts "
            f"{', '.join(zero_recall) or 'some classes'}. It has collapsed toward "
            f"a single class, so its accuracy of {rep['accuracy']:.3f} is not "
            f"evidence that it works. With only {len(set(groups)):,} spatial "
            f"group(s), holding out whole localities leaves the model no basis "
            f"for placing an area it has never seen. This result should be "
            f"reported as a failure to generalise, not as a model."
        )
    elif barely_better:
        warning = (
            f"Accuracy {rep['accuracy']:.3f} is close to the {chance:.3f} chance "
            f"line for {n_classes} balanced classes. Treat as weak."
        )
    if warning:
        print(f"\n    !! {warning}")

    import joblib
    joblib.dump({"pipeline": clf, "bands": BANDS,
                 "thresholds": [float(q1), float(q2)],
                 "features": {"numeric": numeric, "categorical": categorical}},
                models_dir / "price_band_classifier.joblib")

    payload["classification"] = {
        "task": "Price-band classification (3 classes)",
        "labels": BANDS,
        "thresholds_per_sqft": [round(float(q1)), round(float(q2))],
        "label_note": (
            "Bands are the dataset's own terciles of price per sq.ft. Because "
            "the label is derived from the target, this is a discretised view of "
            "the regression problem, not independent information."
        ),
        "split": "GroupShuffleSplit by locality/ward — no locality spans the split",
        "train_rows": int(len(tr)), "test_rows": int(len(te)),
        "accuracy": round(rep["accuracy"], 4),
        "macro_f1": round(rep["macro avg"]["f1-score"], 4),
        "weighted_f1": round(rep["weighted avg"]["f1-score"], 4),
        "roc_auc_ovr_macro": round(auc, 4) if auc else None,
        "per_class": {
            b: {k: round(v, 4) for k, v in rep.get(b, {}).items()} for b in BANDS
        },
        "confusion_matrix": {"labels": BANDS, "matrix": cm.tolist()},
        "chance_accuracy": round(chance, 4),
        "degenerate": degenerate,
        "usable": not degenerate and not barely_better,
        "warning": warning,
        "classes_never_predicted": zero_recall,
    }

    fig, ax = plt.subplots(figsize=(4.6, 4.0))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(3), BANDS, rotation=30, ha="right")
    ax.set_yticks(range(3), BANDS)
    for i in range(3):
        for j in range(3):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() * 0.55 else "#1F2430")
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
    ax.set_title(f"{cfg.display} — price-band confusion matrix", color=NAVY,
                 fontweight="bold", fontsize=10)
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout(); fig.savefig(art / "confusion_matrix.png", dpi=140); plt.close(fig)

    # ---------------------------------------------- 2. clustering
    print("\n[2] LOCALITY CLUSTERING")
    loc = (df.groupby(cfg.locality_column)
             .agg(median_psf=(cfg.target, "median"),
                  spread_psf=(cfg.target, "std"),
                  listings=(cfg.target, "size"),
                  median_area=(numeric[0], "median"))
             .dropna())
    loc = loc[loc["listings"] >= 5]
    print(f"    {len(loc)} localities with >= 5 records")

    clustering: dict[str, Any] = {"available": False}
    if len(loc) >= 12:
        Z = StandardScaler().fit_transform(loc.to_numpy(dtype=float))
        by_k: dict[int, dict[str, float]] = {}
        for k in range(2, min(9, len(loc) - 1)):
            km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10).fit(Z)
            by_k[k] = cluster_validity(Z, km.labels_)

        scores = {k: v["silhouette"] for k, v in by_k.items()}
        # Each index votes for its own optimum. Silhouette decides — it is the
        # one this project has always reported — but the other two are recorded
        # so a disagreement cannot be quietly dropped.
        picks = {
            "silhouette": max(by_k, key=lambda k: by_k[k]["silhouette"]),
            "davies_bouldin": min(by_k, key=lambda k: by_k[k]["davies_bouldin"]),
            "calinski_harabasz": max(by_k, key=lambda k: by_k[k]["calinski_harabasz"]),
        }
        best_k = picks["silhouette"]
        best_sil = by_k[best_k]["silhouette"]
        agree = len(set(picks.values())) == 1

        km = KMeans(n_clusters=best_k, random_state=RANDOM_STATE, n_init=10).fit(Z)
        loc["cluster"] = km.labels_
        print(f"    k chosen by silhouette: k={best_k} (score {best_sil:.4f})")
        print(f"    silhouette by k: {scores}")
        for name, k in picks.items():
            print(f"      {name:<20} prefers k={k}")
        print(f"    indices {'AGREE' if agree else 'DISAGREE'} on k — "
              f"{'the structure survives the choice of index'
                 if agree else 'k is index-dependent, so treat it as one view'}")

        summary = []
        for c in sorted(set(km.labels_)):
            grp = loc[loc["cluster"] == c]
            summary.append({
                "cluster": int(c),
                "localities": int(len(grp)),
                "median_psf": round(float(grp["median_psf"].median())),
                "examples": [str(x) for x in grp.index[:5]],
            })
            print(f"      cluster {c}: {len(grp):>3} localities, "
                  f"median Rs {grp['median_psf'].median():,.0f}/sq.ft — "
                  f"{', '.join(str(x)[:18] for x in grp.index[:3])}")

        joblib.dump({"kmeans": km, "index": list(loc.index),
                     "labels": km.labels_.tolist()},
                    models_dir / "locality_clusters.joblib")
        clustering = {
            "available": True,
            "method": "KMeans on locality-level features (unsupervised ML)",
            "features": ["median price/sq.ft", "price spread", "listing volume",
                         "median area"],
            "k": int(best_k),
            "k_selection": "highest silhouette score, not assumed",
            "silhouette": round(best_sil, 4),
            "silhouette_by_k": scores,
            "validity_by_k": {str(k): v for k, v in by_k.items()},
            "chosen_k_by_index": {n: int(k) for n, k in picks.items()},
            "indices_agree_on_k": agree,
            "validity_note": (
                "Three indices, one decision. Silhouette selects k; "
                "Davies-Bouldin (lower is better) and Calinski-Harabasz "
                "(higher is better) are reported alongside so a disagreement "
                "is visible. When they disagree, k is a property of the index "
                "rather than of the data."
                if agree else
                "The three indices do NOT choose the same k. The clustering is "
                "reported as one defensible view, not as the structure of the "
                "data."
            ),
            "localities_clustered": int(len(loc)),
            "clusters": summary,
            "assignments": {str(i): int(c) for i, c in
                            zip(loc.index, loc["cluster"], strict=True)},
            "note": (
                "Clusters group localities that behave similarly on price level, "
                "spread, volume and size. They are not official zones and carry "
                "no planning meaning."
            ),
        }
    else:
        clustering["reason"] = (
            f"Only {len(loc)} localities have 5+ records — too few to cluster "
            "meaningfully.")
        print(f"    skipped: {clustering['reason']}")
    payload["clustering"] = clustering

    # ---------------------------------------------- 3. anomaly detection
    print("\n[3] ANOMALY DETECTION (three detectors, then their agreement)")
    anom_feats = [c for c in numeric if df[c].notna().sum() > len(df) * 0.5]
    A = df[anom_feats].fillna(df[anom_feats].median())
    As = StandardScaler().fit_transform(A)

    iso = IsolationForest(contamination=CONTAMINATION, random_state=RANDOM_STATE,
                          n_estimators=200)
    flags = iso.fit_predict(As)
    n_out = int((flags == -1).sum())
    print(f"    features: {len(anom_feats)} | flagged {n_out:,} of {len(df):,} "
          f"({n_out / len(df):.1%}) at contamination={CONTAMINATION}")

    # Two more detectors on the same rows, same features, same 5% budget. They
    # define "unusual" differently: isolation depth, local density relative to
    # neighbours, and density-connectivity.
    lof = LocalOutlierFactor(n_neighbors=20, contamination=CONTAMINATION)
    lof_flags = lof.fit_predict(As) == -1
    print(f"    LOF (local density, k=20)          flagged {int(lof_flags.sum()):,}")

    eps = _dbscan_eps(As, DBSCAN_MIN_SAMPLES, CONTAMINATION)
    db = DBSCAN(eps=eps, min_samples=DBSCAN_MIN_SAMPLES).fit(As)
    db_flags = db.labels_ == -1
    print(f"    DBSCAN (eps={eps:.3f} calibrated to {CONTAMINATION:.0%}) "
          f"flagged {int(db_flags.sum()):,}")

    agreement = detector_agreement({
        "isolation_forest": flags == -1,
        "lof": lof_flags,
        "dbscan": db_flags,
    })
    for pair, v in agreement["pairwise"].items():
        print(f"      {pair:<38} Jaccard {v['jaccard']:.3f} "
              f"({v['both']:,} rows in common)")
    print(f"    all three agree on {agreement['flagged_by_all']:,} rows of the "
          f"{agreement['flagged_by_any']:,} flagged by any "
          f"({agreement['unanimous_share_of_any']:.1%})")

    joblib.dump({"model": iso, "features": anom_feats},
                models_dir / "anomaly_detector.joblib")
    payload["anomaly"] = {
        "method": "Isolation Forest (unsupervised ML)",
        "features": anom_feats,
        "contamination": CONTAMINATION,
        "flagged": n_out,
        "total": int(len(df)),
        "detectors": {
            "isolation_forest": {"flagged": n_out,
                                 "defines_unusual_as": "few splits needed to isolate"},
            "lof": {"flagged": int(lof_flags.sum()), "n_neighbors": 20,
                    "defines_unusual_as": "lower local density than its neighbours"},
            "dbscan": {"flagged": int(db_flags.sum()), "eps": round(eps, 4),
                       "min_samples": DBSCAN_MIN_SAMPLES,
                       "defines_unusual_as": "not density-reachable from a core point",
                       "eps_note": (
                           "DBSCAN has no contamination parameter. eps is the "
                           f"{1 - CONTAMINATION:.0%} quantile of the distance to "
                           f"the {DBSCAN_MIN_SAMPLES}th nearest neighbour, so all "
                           "three detectors work to the same budget and the "
                           "comparison is about which rows, not how many.")},
        },
        "agreement": agreement,
        "agreement_note": (
            "Three detectors, one feature matrix, one 5% budget. Jaccard is "
            "used because agreement on the ~95% of rows nobody flagged is not "
            "informative. Rows all three flag are unusual under three "
            "different definitions; rows only one flags say more about that "
            "detector than about the property."
        ),
        "note": (
            "Flags records that are unusual across their whole feature vector, "
            "which is a different question from the price-interval check: that "
            "asks whether a price is far from the model, this asks whether the "
            "record itself is atypical."
        ),
        "caveat": (
            "An anomaly is not evidence of anything wrong. Contamination is set "
            "at 5% by assumption, so roughly 5% of records will be flagged "
            "whatever the data looks like."
        ),
    }

    (art / "extra_models.json").write_text(json.dumps(payload, indent=2),
                                           encoding="utf-8")
    print(f"\n  wrote {art / 'extra_models.json'}")
    print(f"  models -> {models_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
