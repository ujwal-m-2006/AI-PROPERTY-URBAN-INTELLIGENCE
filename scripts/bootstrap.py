"""Rebuild everything a fresh clone does not carry.

`data/raw/` (212 MB) and `models/` (176 MB) are deliberately not in git — every
byte of both is reproducible from the flows in this repo, and one model file
alone is 68 MB. What IS committed is `data/processed/` and `ml/artifacts/`, so a
clone can serve the API and show every metric immediately. This script exists to
rebuild the rest.

    python scripts/bootstrap.py            # everything, in dependency order
    python scripts/bootstrap.py --ingest   # data layers only
    python scripts/bootstrap.py --train    # models only (needs processed data)
    python scripts/bootstrap.py --check    # verify without changing anything

ORDER MATTERS. The ward layers must exist before the gazetteer (which names
wards), the gazetteer before the Chennai ward ingest (which draws Tamil names
from it), and all processed layers before training (GIS features join to them).
Each step is skipped when its output is already present and non-trivial, so
re-running is cheap and safe.

Network steps are polite and cached: every ingest reuses an existing download
rather than re-fetching, so an interrupted run resumes rather than restarting.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
MODELS = ROOT / "models"

PY = sys.executable

# (label, script, produces, needs_network)
INGEST: list[tuple[str, str, Path, bool]] = [
    ("GBA 369 wards", "etl/flows/ingest_gba_wards.py",
     PROCESSED / "gba_wards.geojson", True),
    ("Locality gazetteer — Bengaluru", "etl/flows/ingest_locality_gazetteer.py",
     PROCESSED / "locality_gazetteer_bengaluru.json", True),
    ("Locality gazetteer — Chennai", "etl/flows/ingest_locality_gazetteer.py chennai",
     PROCESSED / "locality_gazetteer_chennai.json", True),
    ("GCC 200 wards + Tamil names", "etl/flows/ingest_chennai_wards.py",
     PROCESSED / "chennai_wards.geojson", False),
    ("OSM amenities — Bengaluru", "etl/flows/ingest_osm_amenities.py bengaluru",
     PROCESSED / "osm_amenities.json", True),
    ("OSM amenities — Chennai", "etl/flows/ingest_osm_amenities.py chennai",
     PROCESSED / "osm_amenities_chennai.json", True),
    ("District + taluk boundaries", "etl/flows/ingest_admin_boundaries.py",
     PROCESSED / "admin_subdistricts_bengaluru.geojson", True),
    ("Revenue sheets (taluk/hobli/village/survey)", "etl/flows/ingest_revenue_maps.py",
     PROCESSED / "revenue_parcels.geojson", True),
    ("Road width map", "etl/flows/ingest_road_network.py",
     PROCESSED / "road_network_bengaluru.geojson", True),
    ("Reported flooding locations", "etl/flows/ingest_flood_locations.py",
     PROCESSED / "flood_locations_bengaluru.geojson", True),
]

TRAIN: list[tuple[str, str, Path]] = [
    ("Price model — Bengaluru", "ml/pipelines/train_city_model.py bengaluru",
     MODELS / "bengaluru" / "price_model.joblib"),
    ("Price model — Chennai", "ml/pipelines/train_city_model.py chennai",
     MODELS / "chennai" / "price_model.joblib"),
    ("Classification / clustering / anomaly — Bengaluru",
     "ml/pipelines/train_extra_models.py bengaluru",
     MODELS / "bengaluru" / "price_band_classifier.joblib"),
    ("Classification / clustering / anomaly — Chennai",
     "ml/pipelines/train_extra_models.py chennai",
     MODELS / "chennai" / "price_band_classifier.joblib"),
    ("Negotiation band (quantile + CQR) — Bengaluru",
     "ml/pipelines/train_advisory_models.py bengaluru",
     MODELS / "bengaluru" / "quantile_band.joblib"),
    ("Negotiation band (quantile + CQR) — Chennai",
     "ml/pipelines/train_advisory_models.py chennai",
     MODELS / "chennai" / "quantile_band.joblib"),
    ("Planning models / ablation — Bengaluru",
     "ml/pipelines/train_planning_models.py bengaluru",
     ROOT / "ml" / "artifacts" / "bengaluru" / "planning_models.json"),
    ("Planning models / ablation — Chennai",
     "ml/pipelines/train_planning_models.py chennai",
     ROOT / "ml" / "artifacts" / "chennai" / "planning_models.json"),
    ("Future price — Bengaluru", "ml/pipelines/train_future_price.py bengaluru",
     ROOT / "ml" / "artifacts" / "bengaluru" / "future_price.json"),
    ("Future price — Chennai", "ml/pipelines/train_future_price.py chennai",
     ROOT / "ml" / "artifacts" / "chennai" / "future_price.json"),
]

MIN_BYTES = 500


def present(path: Path) -> bool:
    return path.exists() and path.stat().st_size > MIN_BYTES


def run(label: str, command: str) -> bool:
    print(f"\n  → {label}")
    print(f"    {command}")
    started = time.time()
    proc = subprocess.run([PY, *command.split()], cwd=ROOT)
    took = time.time() - started
    if proc.returncode == 0:
        print(f"    done in {took:.0f}s")
        return True
    print(f"    FAILED (exit {proc.returncode}) after {took:.0f}s")
    return False


def stage(title: str, items, force: bool) -> tuple[int, int, list[str]]:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}")
    ran = skipped = 0
    failed: list[str] = []
    for entry in items:
        label, command, produces = entry[0], entry[1], entry[2]
        if not force and present(produces):
            print(f"  ✓ {label:<52} already present")
            skipped += 1
            continue
        if run(label, command):
            ran += 1
        else:
            failed.append(label)
    return ran, skipped, failed


def check() -> int:
    print(f"\n{'=' * 72}\n  BOOTSTRAP CHECK — what exists, what does not"
          f"\n{'=' * 72}")
    missing = 0
    for title, items in (("Data layers", INGEST), ("Models", TRAIN)):
        print(f"\n  {title}")
        for entry in items:
            ok = present(entry[2])
            missing += 0 if ok else 1
            mark = "present" if ok else "MISSING"
            print(f"    [{mark:>7}] {entry[0]}")
    print(f"\n  {missing} artefact(s) missing.")
    if missing:
        print("  Run: python scripts/bootstrap.py")
    return 0 if missing == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ingest", action="store_true", help="data layers only")
    ap.add_argument("--train", action="store_true", help="models only")
    ap.add_argument("--check", action="store_true", help="report, change nothing")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even when the output already exists")
    args = ap.parse_args()

    if args.check:
        return check()

    do_ingest = args.ingest or not args.train
    do_train = args.train or not args.ingest

    print("Bootstrap — rebuilding what git does not carry")
    print("  data/raw and models/ are reproducible and therefore untracked.")
    print("  Ingests are cached and resumable; re-running is cheap.")

    failed: list[str] = []
    if do_ingest:
        ran, skipped, bad = stage("DATA LAYERS (network)", INGEST, args.force)
        print(f"\n  {ran} run, {skipped} already present, {len(bad)} failed")
        failed += bad

    if do_train:
        if not present(PROCESSED / "gba_wards.geojson"):
            print("\n  Refusing to train: processed data is missing. "
                  "Run the ingest stage first.")
            return 2
        ran, skipped, bad = stage("MODELS (cpu-bound, several minutes)",
                                  TRAIN, args.force)
        print(f"\n  {ran} run, {skipped} already present, {len(bad)} failed")
        failed += bad

    print(f"\n{'=' * 72}")
    if failed:
        print(f"  {len(failed)} step(s) failed:")
        for f in failed:
            print(f"    - {f}")
        print("\n  Most failures here are network ones. Re-run the script — every")
        print("  step is cached, so it resumes rather than starting over.")
        return 1

    print("  Bootstrap complete. Verify with:")
    print("    cd backend && PYTHONPATH=. python scripts/e2e_check.py")
    print("    cd backend && PYTHONPATH=. python scripts/module_check.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
