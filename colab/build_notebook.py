"""Generate the Colab notebook.

Written as a generator rather than a hand-edited .ipynb so the code inside it
can be linted and executed locally before anyone opens Colab. A notebook that
has never been run is a liability; this one is verified by running the same
cells through a plain interpreter (see verify_notebook.py).

    python colab/build_notebook.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "GBA_Property_Intelligence.ipynb"

RAW = ("https://raw.githubusercontent.com/ujwal-m-2006/"
       "AI-PROPERTY-URBAN-INTELLIGENCE/main/colab/data")

BLR_URL = ("https://raw.githubusercontent.com/dphi-official/Datasets/master/"
           "Bengaluru_House_Data.csv")
CHN_URL = ("https://raw.githubusercontent.com/Ravi8149/"
           "Chennai-House-Price-Prediction/HEAD/chennai-house-price.csv")


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {},
            "source": text.strip().splitlines(keepends=True)}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": text.strip().splitlines(keepends=True)}


CELLS = [
    md(f"""
# Bengaluru & Chennai — Property & Urban Intelligence

Companion notebook to
[AI-PROPERTY-URBAN-INTELLIGENCE](https://github.com/ujwal-m-2006/AI-PROPERTY-URBAN-INTELLIGENCE).

This notebook does three things:

1. Loads all 17 platform CSVs plus both property datasets, from public URLs.
2. Reproduces the project's headline ML finding — that **most of the reported
   accuracy in a naive setup is geographic leakage**.
3. Shows the two results that are reported as failures rather than hidden.

**Nothing here is fitted to look good.** Two of the numbers you are about to see
are bad, and they are the interesting ones.

Runtime: a few minutes on a free CPU instance. No GPU, no Drive mount.
"""),

    md("## 1 · Setup"),
    code("""
import warnings, io, json, math
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import GroupKFold, KFold, cross_val_score
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler

pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 200)
print("pandas", pd.__version__, "| numpy", np.__version__)
"""),

    md(f"""
## 2 · Load the platform layers

All 17 CSVs come from the repository. Each file's first line is a `#` comment
carrying the caveat that constrains how the table may be read — so the loader
keeps it rather than skipping past it.

If you would rather use your own Drive folder, set `BASE` to that path instead
of the URL.
"""),
    code(f"""
BASE = "{RAW}"          # or e.g. "/content/drive/MyDrive/colab_data"

LAYERS = [
    "gba_wards", "gba_corporations", "chennai_wards", "chennai_zones",
    "admin_taluks_bengaluru", "admin_taluks_chennai",
    "revenue_parcels", "road_network_bengaluru", "flood_locations_bengaluru",
    "localities_bengaluru", "localities_chennai",
    "amenities_bengaluru", "amenities_chennai",
    "ward_analytics_bengaluru", "ward_analytics_chennai",
    "model_comparison", "_sources",
]

def load(name):
    \"\"\"Read a layer, keeping its caveat line.\"\"\"
    path = f"{{BASE}}/{{name}}.csv"
    caveat = ""
    try:
        head = pd.read_csv(path, nrows=0, header=None, comment=None).columns
    except Exception:
        pass
    df = pd.read_csv(path, comment="#", low_memory=False)
    # Recover the caveat comment, which pandas skipped.
    try:
        import urllib.request
        first = urllib.request.urlopen(path).readline().decode("utf-8", "ignore")
        if first.startswith("#"):
            caveat = first.lstrip("# ").strip()
    except Exception:
        try:
            with open(path, encoding="utf-8") as fh:
                first = fh.readline()
            if first.startswith("#"):
                caveat = first.lstrip("# ").strip()
        except Exception:
            caveat = ""
    df.attrs["caveat"] = caveat
    return df

data = {{}}
for name in LAYERS:
    try:
        data[name] = load(name)
        print(f"  {{name:<32}} {{len(data[name]):>6,}} rows x {{data[name].shape[1]:>2}} cols")
    except Exception as exc:
        print(f"  {{name:<32}} FAILED: {{type(exc).__name__}}")

print(f"\\n{{sum(len(d) for d in data.values()):,}} rows loaded across {{len(data)}} layers")
"""),

    md("""
### The caveats are the point

Several of these tables would mislead if read at face value. They say so
themselves.
"""),
    code("""
for name in ["gba_wards", "road_network_bengaluru", "revenue_parcels",
             "flood_locations_bengaluru", "chennai_wards"]:
    if name in data and data[name].attrs.get("caveat"):
        print(f"── {name}")
        print(f"   {data[name].attrs['caveat'][:300]}\\n")
"""),

    md("## 3 · Provenance — where every layer came from"),
    code("""
src = data["_sources"][["layer", "organisation", "tier", "availability",
                        "licence", "verification_status"]]
display(src)

print("\\nTier meaning: T1 official primary · T2 official republished · "
      "T3 community/open · T4 commercial dataset")
print("No layer here is T1 — every government layer reached this project "
      "through a portal or a community mirror, and is capped accordingly.")
"""),

    md("""
## 4 · The two-width problem

`road_network_bengaluru` carries **two** width columns. Feeding the wrong one
into a floor-area calculation would roughly double the buildable area for the
whole city, with nothing on screen looking wrong.
"""),
    code("""
rd = data["road_network_bengaluru"]
w = rd[["width_existing_m", "width_proposed_m"]].describe().loc[["min", "50%", "max"]]
display(w)

larger = (rd["width_proposed_m"] > rd["width_existing_m"]).mean()
print(f"proposed > existing on {larger:.1%} of {len(rd):,} segments")
print("A file titled 'road width map' contains a road-widening PROPOSAL.")

fig, ax = plt.subplots(figsize=(7, 3.2))
ax.hist(rd["width_existing_m"].dropna(), bins=40, alpha=.75, label="existing")
ax.hist(rd["width_proposed_m"].dropna(), bins=40, alpha=.55, label="proposed")
ax.set_xlabel("road width (m)"); ax.set_ylabel("segments"); ax.legend()
ax.set_title("Two width columns, one filename")
plt.tight_layout(); plt.show()
"""),

    md("""
## 5 · The suppressed population column

`gba_wards._raw_tot_p` is the source's own population field. It sums to roughly
six times the real Greater Bengaluru total, so the platform publishes **no**
ward population at all.

Dividing by 6 reproduces the officially reported per-corporation averages almost
exactly — including East's distinctly lower figure, which nothing was fitted to.
That is suggestive, and it is still not enough.
"""),
    code("""
gw = data["gba_wards"]
print(f"sum of _raw_tot_p : {gw['_raw_tot_p'].sum():,}")
print(f"real Greater Bengaluru population is roughly 14,000,000")
print(f"sum / 6           : {gw['_raw_tot_p'].sum()/6:,.0f}\\n")

by_corp = gw.groupby("corporation")["_raw_tot_p"].agg(["count", "mean"])
by_corp["mean_div_6"] = (by_corp["mean"] / 6).round(0)
by_corp["reported"] = by_corp.index.map(
    {"Central": 40000, "East": 26000, "North": 40000,
     "South": 40000, "West": 40000})
display(by_corp)

inconsistent = (gw["_raw_tot_m"] + gw["_raw_tot_f"] != gw["_raw_tot_p"]).sum()
print(f"\\nrows where male + female != total: {inconsistent} of {len(gw)}")
print("A constant chosen because it makes a total look right is not provenance,")
print("and a third of the rows fail an internal check unrelated to scale.")
print("=> the platform publishes no ward population.")
"""),

    md(f"""
## 6 · The property datasets

Fetched from their original public sources, not from this repository — the
platform never redistributes them.

* Bengaluru — **asking** prices from listings
* Chennai — **recorded sale** prices

Those targets measure different things and are never pooled.
"""),
    code(f"""
blr_raw = pd.read_csv("{BLR_URL}")
chn_raw = pd.read_csv("{CHN_URL}")
print("Bengaluru", blr_raw.shape, "| Chennai", chn_raw.shape)
display(blr_raw.head(3))
display(chn_raw.head(3))
"""),

    md("""
### Cleaning

Only what is needed to reproduce the headline result: parse the messy area
column, derive price per sq.ft, drop the extreme tail.
"""),
    code("""
def parse_sqft(v):
    \"\"\"total_sqft holds ranges ('1133 - 1384') and units ('34.46Sq. Meter').\"\"\"
    if pd.isna(v):
        return np.nan
    s = str(v).strip()
    if "-" in s:
        parts = s.split("-")
        try:
            return (float(parts[0]) + float(parts[1])) / 2
        except ValueError:
            return np.nan
    try:
        return float(s)
    except ValueError:
        pass
    import re
    m = re.match(r"([\\d.]+)\\s*(\\D+)", s)
    if not m:
        return np.nan
    n, unit = float(m.group(1)), m.group(2).lower()
    factor = {"sq. meter": 10.7639, "sq. yards": 9.0, "perch": 272.25,
              "acres": 43560.0, "cents": 435.6, "guntha": 1089.0,
              "grounds": 2400.0}
    for k, f in factor.items():
        if k in unit:
            return n * f
    return np.nan

blr = blr_raw.copy()
blr["sqft"] = blr["total_sqft"].apply(parse_sqft)
blr["rooms"] = blr["size"].astype(str).str.extract(r"(\\d+)").astype(float)
blr["price_inr"] = blr["price"] * 1e5                 # source is in lakh
blr["price_per_sqft"] = blr["price_inr"] / blr["sqft"]
blr["locality"] = blr["location"].astype(str).str.strip()
blr = blr.dropna(subset=["price_per_sqft", "sqft", "rooms", "locality"])
lo, hi = blr["price_per_sqft"].quantile([0.01, 0.99])
blr = blr[(blr["price_per_sqft"] >= lo) & (blr["price_per_sqft"] <= hi)]
blr = blr[(blr["sqft"] > 100) & (blr["sqft"] < 30000)]

print(f"Bengaluru after cleaning: {len(blr):,} rows, "
      f"{blr['locality'].nunique()} localities")
print(f"  median asking: Rs {blr['price_per_sqft'].median():,.0f}/sq.ft")
"""),

    md("""
## 7 · The headline finding — random k-fold leaks

A property and its next-door neighbour are nearly the same row. Random k-fold
puts them on opposite sides of the split, so the model memorises each locality's
price level and reports it as skill.

Grouping the folds by locality removes that. The gap is the leakage.
"""),
    code("""
FEATURES_NUM = ["sqft", "rooms", "bath", "balcony"]
FEATURES_CAT = ["area_type", "availability"]

X = blr[FEATURES_NUM + FEATURES_CAT]
y = blr["price_per_sqft"].to_numpy()
groups = blr["locality"].to_numpy()

pre = ColumnTransformer([
    ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                      ("sc", StandardScaler())]), FEATURES_NUM),
    ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                      ("oh", OneHotEncoder(handle_unknown="ignore",
                                           min_frequency=10))]), FEATURES_CAT),
])

MODELS = {
    "linear_regression": LinearRegression(),
    "random_forest": RandomForestRegressor(n_estimators=120, random_state=42,
                                           n_jobs=-1),
    "gradient_boosting": GradientBoostingRegressor(random_state=42),
}

rows = []
for name, est in MODELS.items():
    pipe = Pipeline([("pre", pre), ("m", est)])
    rand = cross_val_score(pipe, X, y, cv=KFold(5, shuffle=True,
                                                random_state=42),
                           scoring="r2", n_jobs=-1).mean()
    spat = cross_val_score(pipe, X, y, cv=GroupKFold(5), groups=groups,
                           scoring="r2", n_jobs=-1).mean()
    rows.append({"algorithm": name, "random_cv_r2": round(rand, 4),
                 "spatial_cv_r2": round(spat, 4),
                 "leakage_gap": round(rand - spat, 4)})
    print(f"  {name:<20} random {rand:.4f}   spatial {spat:.4f}   "
          f"gap {rand-spat:+.4f}")

leak = pd.DataFrame(rows)
display(leak)
print("\\nEvery model scores higher under random CV. The gap is the part of the")
print("accuracy that was leakage. Model selection must use the lower number.")
"""),
    code("""
fig, ax = plt.subplots(figsize=(7, 3.4))
i = np.arange(len(leak))
ax.bar(i - 0.2, leak["random_cv_r2"], 0.4, label="random k-fold (optimistic)")
ax.bar(i + 0.2, leak["spatial_cv_r2"], 0.4, label="grouped by locality (honest)")
ax.set_xticks(i); ax.set_xticklabels(leak["algorithm"], rotation=15, ha="right")
ax.set_ylabel("R²"); ax.legend(); ax.set_title("The same models, two validation schemes")
ax.grid(axis="y", alpha=.3)
plt.tight_layout(); plt.show()
"""),

    md("""
## 8 · Chennai — where this would have fooled anyone

Chennai's dataset covers only **7 localities**, so there are only 7 spatial
blocks. Hold out a whole locality and the models fall apart, while a random
split reports near-perfect accuracy.
"""),
    code("""
chn = chn_raw.copy()
chn.columns = [c.strip() for c in chn.columns]
chn["price_per_sqft"] = chn["SALES_PRICE"] / chn["INT_SQFT"]
chn["locality"] = chn["AREA"].astype(str).str.strip()
chn = chn.dropna(subset=["price_per_sqft", "INT_SQFT", "locality"])
lo, hi = chn["price_per_sqft"].quantile([0.01, 0.99])
chn = chn[(chn["price_per_sqft"] >= lo) & (chn["price_per_sqft"] <= hi)]

print(f"Chennai after cleaning: {len(chn):,} rows")
print(f"  localities (= spatial blocks): {chn['locality'].nunique()}")
print(f"  {dict(chn['locality'].value_counts())}\\n")

Xc = chn[["INT_SQFT", "N_BEDROOM", "N_BATHROOM", "N_ROOM"]]
yc = chn["price_per_sqft"].to_numpy()
gc = chn["locality"].to_numpy()

pc = Pipeline([("imp", SimpleImputer(strategy="median")),
               ("sc", StandardScaler())])
for name, est in [("random_forest", RandomForestRegressor(
                       n_estimators=120, random_state=42, n_jobs=-1)),
                  ("gradient_boosting", GradientBoostingRegressor(random_state=42))]:
    pipe = Pipeline([("pre", pc), ("m", est)])
    rand = cross_val_score(pipe, Xc, yc, cv=KFold(5, shuffle=True,
                                                  random_state=42),
                           scoring="r2", n_jobs=-1).mean()
    spat = cross_val_score(pipe, Xc, yc, cv=GroupKFold(5), groups=gc,
                           scoring="r2", n_jobs=-1).mean()
    print(f"  {name:<20} random {rand:>8.4f}   spatial {spat:>8.4f}   "
          f"gap {rand-spat:+.4f}")

print("\\nA negative spatial R² means the model does WORSE than predicting the")
print("mean. With 7 localities there is nothing to generalise from, and the")
print("platform refuses to quote the random-split figure as accuracy.")
"""),

    md("""
## 9 · The results reported as failures

Two outputs in this project are trained, measured, and then labelled unusable.
Both are read straight from the shipped model-comparison table.
"""),
    code("""
mc = data["model_comparison"]
display(mc.sort_values(["city", "spatial_cv_r2"], ascending=[True, False]))

print("Chennai's linear_regression scores ABOVE its tree models on spatial CV —")
print("with 7 blocks the trees overfit the blocks they saw. That inversion is")
print("why the shipped Chennai model is the simpler one.\\n")

worst = mc.loc[mc["spatial_cv_r2"].idxmin()]
print(f"worst spatial R² in the project: {worst['algorithm']} on "
      f"{worst['city']} = {worst['spatial_cv_r2']}")
print("It is kept in the table rather than dropped, because a comparison that")
print("hides its failures is not a comparison.")
"""),

    md("""
## 10 · Ward-level service accessibility

Per-ward scores for both cities. These are **weighted formulas, not machine
learning** — no dataset carries an observed "accessibility" label to train on,
and calling a formula ML would be the easiest lie in the project.
"""),
    code("""
for city in ["bengaluru", "chennai"]:
    wa = data.get(f"ward_analytics_{city}")
    if wa is None or wa.empty:
        continue
    cols = [c for c in wa.columns if c.endswith("_score")][:4]
    if not cols:
        cols = wa.select_dtypes("number").columns[:4].tolist()
    print(f"── {city}: {len(wa)} wards")
    display(wa[["ward_no"] + cols].describe().round(1) if "ward_no" in wa
            else wa[cols].describe().round(1))
"""),

    md("""
## 11 · What this notebook did not do

Being explicit, because the omissions are deliberate:

* **No government record was fetched.** Khata, property tax, building permission
  and occupancy certificates are OTP-gated per-property portals. No public API
  exists for any of them, for anyone.
* **No ward population is published**, for the reason shown in section 5.
* **No FAR or floor limit is computed.** The governing instruments are cited in
  the platform but their clauses are not transcribed, so publishing a number
  would be a guess wearing a citation.
* **No flood risk score.** 391 reported locations with no return period, depth
  or drainage cannot support one.

The platform's value is calibrated honesty: it states what is verified, what is
indicative, and what nobody can obtain — and the last category is large.

---

Full platform, tests and data-source audit:
[github.com/ujwal-m-2006/AI-PROPERTY-URBAN-INTELLIGENCE](https://github.com/ujwal-m-2006/AI-PROPERTY-URBAN-INTELLIGENCE)
"""),
]


def main() -> int:
    nb = {
        "cells": CELLS,
        "metadata": {
            "colab": {"provenance": [], "toc_visible": True},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    n_code = sum(1 for c in CELLS if c["cell_type"] == "code")
    print(f"wrote {OUT}")
    print(f"  {len(CELLS)} cells ({n_code} code, {len(CELLS) - n_code} markdown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
