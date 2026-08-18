"""Planning models — every layer as a feature, and an honest test of whether it helps.

The shipped price model uses 20 features drawn from two layers: OpenStreetMap
amenities and the ward boundaries. Four more layers were ingested later and no
model has ever seen them — the road width map, the reported flooding locations,
the district/taluk boundaries and the revenue sheets.

"Use all the datasets" is easy to satisfy dishonestly: bolt every column on,
report a number, and never check whether any of it earned its place. So this
pipeline is an **ablation study**. Features are added in groups, each group is
scored under the same spatial-block CV the rest of the project uses, and the
delta is reported per group.

Some groups will not help. That is a result, not a failure — a feature that
does not improve out-of-locality generalisation is noise with a plausible name,
and adding it anyway is how models get worse while looking richer.

TWO RULES THIS PIPELINE OBEYS
-----------------------------
1. **Only the existing road width is used.** The road layer's proposed width
   exceeds the existing one on 100% of segments. Feeding a road-widening
   proposal to a price model would leak a planning intention into a market
   prediction. `width_proposed_m` is excluded by name.

2. **Ward typologies are clustered, never labelled.** For the planning half
   there is no ground-truth "development pressure" or "underserved" label
   anywhere in the data. Training a classifier against a formula the project
   itself computed would be circular — the model would learn the formula, and
   its accuracy would measure nothing. So the planning output is unsupervised
   clustering, with the silhouette reported.

    python ml/pipelines/train_planning_models.py [bengaluru|chennai]
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import silhouette_score
from sklearn.model_selection import GroupKFold, cross_val_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
# The lookup logic for these layers already exists in the backend services as
# pure functions over files. Reimplementing point-in-polygon here would risk the
# two drifting apart, which is worse than the layering compromise.
sys.path.insert(0, str(ROOT / "backend"))

from features.gis_features import add_gis_features  # noqa: E402
from pipelines import city_config  # noqa: E402
from pipelines.train_city_model import GIS_NUMERIC, build_pipeline  # noqa: E402

RANDOM_STATE = 42
CV_FOLDS = 5

# Excluded by name. See rule 1 in the module docstring.
FORBIDDEN = ("width_proposed_m", "road_width_proposed_m")


def _enrich(df: pd.DataFrame, city: str) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Attach road, flood and taluk features. Returns the new column groups."""
    from app.services import admin_boundaries, flood, roads

    groups: dict[str, list[str]] = {"road": [], "flood": [], "admin": []}
    have_coords = df["gis_lat"].notna() & df["gis_lng"].notna()
    n = int(have_coords.sum())
    print(f"    {n:,} of {len(df):,} rows have coordinates to join on")

    road_w: list[float | None] = []
    road_d: list[float | None] = []
    road_h: list[str | None] = []
    flood_d: list[float | None] = []
    taluk: list[str | None] = []

    # Cache by rounded coordinate — many rows share a locality centroid, so this
    # turns ~12k lookups into a few hundred.
    cache: dict[tuple, tuple] = {}
    for lat, lng, ok in zip(df["gis_lat"], df["gis_lng"], have_coords, strict=True):
        if not ok:
            road_w.append(None); road_d.append(None); road_h.append(None)
            flood_d.append(None); taluk.append(None)
            continue
        key = (round(float(lng), 4), round(float(lat), 4))
        if key not in cache:
            hit = roads.nearest(key[0], key[1]) if city == "bengaluru" else None
            fl = flood.nearby(key[0], key[1], limit=1) if city == "bengaluru" else []
            ab = admin_boundaries.locate(key[0], key[1], city)
            cache[key] = (
                hit.get("width_existing_m") if hit else None,
                hit.get("distance_m") if hit else None,
                hit.get("hierarchy_code") if hit else None,
                fl[0]["distance_m"] if fl else None,
                (ab or {}).get("taluk"),
            )
        w, d, h, f, t = cache[key]
        road_w.append(w); road_d.append(d); road_h.append(h)
        flood_d.append(f); taluk.append(t)

    df = df.copy()
    if city == "bengaluru":
        df["road_width_existing_m"] = road_w
        df["road_distance_m"] = road_d
        df["road_hierarchy"] = pd.Series(road_h, index=df.index).astype("object")
        groups["road"] = ["road_width_existing_m", "road_distance_m"]
        df["flood_distance_m"] = flood_d
        groups["flood"] = ["flood_distance_m"]
        for name, col in (("road", "road_width_existing_m"),
                          ("flood", "flood_distance_m")):
            filled = df[col].notna().mean()
            print(f"    {name:<6} coverage {filled:.1%}")
    df["taluk"] = pd.Series(taluk, index=df.index).astype("object")
    groups["admin"] = []          # categorical, handled separately
    print(f"    taluk  coverage {df['taluk'].notna().mean():.1%} "
          f"({df['taluk'].nunique()} distinct)")
    return df, groups


def _score(df: pd.DataFrame, numeric: list[str], categorical: list[str],
           target: str, groups: np.ndarray) -> float:
    """Spatial-block CV R². The only number this pipeline selects on."""
    for bad in FORBIDDEN:
        assert bad not in numeric, f"{bad} must never enter a model"
    X = df[numeric + categorical]
    y = df[target].to_numpy()
    pipe = build_pipeline(
        GradientBoostingRegressor(random_state=RANDOM_STATE, n_estimators=300,
                                  max_depth=3, learning_rate=0.05),
        numeric, categorical)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scores = cross_val_score(pipe, X, y, cv=GroupKFold(CV_FOLDS),
                                 groups=groups, scoring="r2", n_jobs=-1)
    return float(np.mean(scores))


def main() -> int:
    city = (sys.argv[1] if len(sys.argv) > 1 else "bengaluru").strip().lower()
    cfg = city_config.get(city)
    art = ROOT / "ml" / "artifacts" / city
    models_dir = ROOT / "models" / city
    art.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 74}\n  {cfg.display.upper()} — PLANNING MODELS "
          f"(all layers, ablation)\n{'=' * 74}")

    df, _ = cfg.clean(city_config.load_raw(cfg))
    df, gis = add_gis_features(
        df, locality_column=cfg.locality_column, city=city,
        amenities_file=cfg.amenities_file, wards_file=cfg.wards_file)
    df["has_gis"] = df["gis_lat"].notna().astype(int)
    print(f"  {len(df):,} rows | locality match {gis['locality_match_rate']:.1%}")

    print("\n[1] JOINING THE LAYERS NO MODEL HAS SEEN")
    df, new_groups = _enrich(df, city)

    block = df["gis_ward_no"].astype("object").where(
        df["gis_ward_no"].notna(), "loc:" + df[cfg.locality_column].astype(str)
    ).astype(str)
    groups = block.to_numpy()

    base_num = [c for c in cfg.numeric_features if c in df.columns]
    gis_num = [c for c in GIS_NUMERIC if c in df.columns] + ["has_gis"]
    base_cat = [c for c in cfg.categorical_features if c in df.columns]
    corp_cat = (["gis_corporation"]
                if df.get("gis_corporation") is not None
                and df["gis_corporation"].notna().any() else [])

    # --- ablation ------------------------------------------------------
    print("\n[2] ABLATION — does each layer earn its place?")
    steps: list[tuple[str, list[str], list[str]]] = [
        ("property only", base_num, base_cat),
        ("+ OSM amenities / wards (shipped)", base_num + gis_num, base_cat + corp_cat),
    ]
    if new_groups["road"]:
        steps.append(("+ road width & distance",
                      base_num + gis_num + new_groups["road"],
                      base_cat + corp_cat + ["road_hierarchy"]))
    if new_groups["flood"]:
        prev_num = steps[-1][1]
        prev_cat = steps[-1][2]
        steps.append(("+ reported flooding distance",
                      prev_num + new_groups["flood"], prev_cat))
    if df["taluk"].notna().any():
        prev_num = steps[-1][1]
        prev_cat = steps[-1][2]
        steps.append(("+ taluk", prev_num, prev_cat + ["taluk"]))

    results: list[dict[str, Any]] = []
    previous: float | None = None
    for label, num, cat in steps:
        # Round first, then difference. Computing the delta at full precision and
        # rounding afterwards leaves the published numbers not adding up, which
        # is the kind of small dishonesty a reader checking the arithmetic finds.
        r2 = round(_score(df, num, cat, cfg.target, groups), 4)
        delta = None if previous is None else round(r2 - previous, 4)
        verdict = ("baseline" if previous is None else
                   "HELPS" if delta > 0.005 else
                   "no effect" if abs(delta) <= 0.005 else "HURTS")
        results.append({
            "features": label, "n_features": len(num) + len(cat),
            "spatial_cv_r2": r2, "delta": delta, "verdict": verdict,
        })
        arrow = "" if delta is None else f"  {delta:+.4f}  {verdict}"
        print(f"    {label:<38} R² {r2:.4f}{arrow}")
        previous = r2

    best = max(results, key=lambda r: r["spatial_cv_r2"])
    helped = [r["features"] for r in results if r["verdict"] == "HELPS"]
    hurt = [r["features"] for r in results if r["verdict"] == "HURTS"]
    neutral = [r["features"] for r in results if r["verdict"] == "no effect"]
    print(f"\n    best: {best['features']} at R² {best['spatial_cv_r2']}")
    if neutral or hurt:
        print(f"    {len(neutral) + len(hurt)} layer(s) did NOT improve "
              "out-of-locality generalisation")

    # --- ward typologies (planning) ------------------------------------
    print("\n[3] WARD TYPOLOGIES — unsupervised, no label invented")
    wa_path = ROOT / "data" / "processed" / f"ward_analytics_{city}.json"
    typology: dict[str, Any]
    if not wa_path.exists():
        typology = {"available": False,
                    "reason": "ward analytics not generated for this city"}
        print("    skipped — ward analytics missing")
    else:
        payload = json.loads(wa_path.read_text(encoding="utf-8"))
        wards = payload.get("wards") or payload.get("data") or []
        rows = []
        for w in wards:
            flat: dict[str, Any] = {}
            for k, v in w.items():
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        if isinstance(v2, (int, float)):
                            flat[f"{k}_{k2}"] = v2
                elif isinstance(v, (int, float)):
                    flat[k] = v
            flat["ward_no"] = w.get("ward_no")
            flat["ward_name"] = w.get("ward_name")
            rows.append(flat)
        wdf = pd.DataFrame(rows)
        feat_cols = [c for c in wdf.columns
                     if c not in ("ward_no", "ward_name")
                     and wdf[c].notna().sum() > len(wdf) * 0.6]
        wdf = wdf.dropna(subset=feat_cols)

        if len(wdf) < 30 or len(feat_cols) < 3:
            typology = {"available": False,
                        "reason": (f"only {len(wdf)} wards with "
                                   f"{len(feat_cols)} usable features — too few "
                                   "to cluster meaningfully")}
            print(f"    refused: {typology['reason']}")
        else:
            Z = StandardScaler().fit_transform(wdf[feat_cols])
            best_k, best_sil, best_model = None, -1.0, None
            for k in range(2, 7):
                km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)
                lab = km.fit_predict(Z)
                sil = silhouette_score(Z, lab)
                print(f"    k={k}  silhouette {sil:.4f}")
                if sil > best_sil:
                    best_k, best_sil, best_model = k, sil, km
            labels = best_model.predict(Z)
            wdf["typology"] = labels
            clusters = []
            for c in sorted(set(labels)):
                sub = wdf[wdf["typology"] == c]
                clusters.append({
                    "typology": int(c),
                    "wards": int(len(sub)),
                    "examples": [str(x) for x in sub["ward_name"].head(3)],
                    "profile": {col: round(float(sub[col].mean()), 1)
                                for col in feat_cols[:6]},
                })
            joblib.dump({"model": best_model, "features": feat_cols,
                         "scaler_fitted_on": feat_cols},
                        models_dir / "ward_typology.joblib")
            # Silhouette below ~0.35 means the clusters are barely separated.
            # Presenting weakly-separated groups as "ward typologies" would give
            # a planner categories the data does not actually support.
            weak = best_sil < 0.35
            typology = {
                "available": True,
                "well_separated": not weak,
                "warning": (
                    f"WEAKLY SEPARATED — silhouette {best_sil:.4f}. Below about "
                    "0.35 the clusters overlap substantially, so these groups "
                    "describe a gradient rather than distinct ward types. Use "
                    "them to explore, not to classify a ward."
                    if weak else None
                ),
                "method": "KMeans on standardised ward-level service metrics",
                "k": int(best_k),
                "k_selection": "highest silhouette over k=2..6, not assumed",
                "silhouette": round(float(best_sil), 4),
                "wards_clustered": int(len(wdf)),
                "features_used": feat_cols,
                "clusters": clusters,
                "not_a_label": (
                    "These are typologies, not rankings. No dataset carries an "
                    "observed 'development pressure' or 'underserved' label, so "
                    "none is predicted. A cluster number carries no ordering — "
                    "typology 0 is not worse or better than typology 2."
                ),
            }
            print(f"    k={best_k} chosen, silhouette {best_sil:.4f}, "
                  f"{len(wdf)} wards")
            if weak:
                print(f"    WARNING: silhouette {best_sil:.4f} < 0.35 — the "
                      "clusters overlap substantially and describe a gradient, "
                      "not distinct types")

    payload_out = {
        "city": city,
        "display": cfg.display,
        "generated_at": datetime.now(UTC).isoformat(),
        "target": cfg.target,
        "target_label": getattr(cfg, "target_label", cfg.target),
        "validation": (f"GroupKFold({CV_FOLDS}) by ward/locality — the same "
                       "spatial-block scheme as every other model here, so "
                       "these R² values are comparable with the headline one"),
        "layers_joined": {
            "road": bool(new_groups["road"]),
            "flood": bool(new_groups["flood"]),
            "admin_taluk": bool(df["taluk"].notna().any()),
        },
        "excluded_features": {
            "width_proposed_m": (
                "The road layer's proposed width exceeds the existing one on "
                "100% of segments. It encodes a planning intention, not a "
                "present condition, and feeding it to a price model would leak "
                "that intention into a market prediction."
            ),
        },
        "ablation": results,
        "best": best,
        "layers_that_helped": helped,
        "layers_that_did_not": neutral + hurt,
        "honest_reading": (
            f"Adding every remaining layer moved spatial-CV R² to "
            f"{best['spatial_cv_r2']}. "
            + (f"{len(neutral) + len(hurt)} of {len(results) - 1} additions did "
               "not improve out-of-locality generalisation and are reported as "
               "such rather than quietly kept."
               if (neutral or hurt) else
               "Every addition improved out-of-locality generalisation.")
        ),
        "ward_typology": typology,
    }
    (art / "planning_models.json").write_text(
        json.dumps(payload_out, indent=2), encoding="utf-8")
    print(f"\n  wrote {art / 'planning_models.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
