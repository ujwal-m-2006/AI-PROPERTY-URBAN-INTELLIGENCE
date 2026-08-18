"""Charts for the Project Review 1 presentation.

Deliberately plain: white background, navy series, one accent, no gridline
clutter, no 3D, no gradients. Every figure is generated from the actual
dataset — none are illustrative.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from pipelines import city_config  # noqa: E402

OUT = ROOT / "ml" / "artifacts" / "review1"
OUT.mkdir(parents=True, exist_ok=True)

NAVY = "#1B365D"
ACCENT = "#C2703A"
GREY = "#8A94A3"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.edgecolor": "#B8C0CC",
    "axes.labelcolor": "#1F2430",
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.titlecolor": NAVY,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.grid": True,
    "grid.color": "#E6EAF0",
    "grid.linewidth": 0.8,
    "xtick.color": "#5C6675",
    "ytick.color": "#5C6675",
})


def save(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=200, facecolor="white")
    plt.close(fig)
    print(f"  {name}")


def main() -> int:
    cfg = city_config.get("bengaluru")
    raw = city_config.load_raw(cfg)
    df, _ = cfg.clean(raw.copy())
    print("generating review-1 charts")

    # 1 — missing values (raw dataset)
    miss = raw.isna().sum()
    miss = miss[miss > 0].sort_values()
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    ax.barh(miss.index, miss.values, color=NAVY)
    for i, v in enumerate(miss.values):
        ax.text(v + 60, i, f"{v:,}", va="center", fontsize=9, color="#5C6675")
    ax.set_xlabel("Missing records")
    ax.set_title("Missing values by column (raw dataset, n = 13,320)")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, miss.max() * 1.18)
    save(fig, "missing_values.png")

    # 2 — outliers, box plots
    fig, axes = plt.subplots(2, 1, figsize=(7.0, 3.2))
    for ax, col, label, ticks in (
        (axes[0], "sqft", "Area (sq.ft)", [0, 10000, 20000, 30000]),
        (axes[1], "price_per_sqft", "Price per sq.ft (INR)",
         [0, 10000, 20000, 30000, 40000]),
    ):
        ax.boxplot(df[col].dropna(), orientation="horizontal", widths=0.5,
                   patch_artist=True,
                   boxprops=dict(facecolor="#DCE4EF", edgecolor=NAVY),
                   medianprops=dict(color=ACCENT, linewidth=2),
                   flierprops=dict(marker="o", markersize=2.5,
                                   markerfacecolor=GREY, markeredgecolor="none",
                                   alpha=0.35))
        ax.set_xlabel(label, fontsize=9.5)
        ax.set_xticks(ticks)
        ax.set_xticklabels([f"{t:,}" for t in ticks], fontsize=9)
        ax.set_yticks([])
        ax.grid(axis="y", visible=False)
    fig.suptitle("Outlier inspection after cleaning", color=NAVY,
                 fontweight="bold", fontsize=11)
    save(fig, "outliers_boxplots.png")

    # 3 — area vs price
    sample = df.sample(min(4000, len(df)), random_state=42)
    fig, ax = plt.subplots(figsize=(6.2, 4.0))
    ax.scatter(sample["sqft"], sample["price_inr"] / 1e5, s=7,
               color=NAVY, alpha=0.30, edgecolors="none")
    ax.set_xlim(0, 6000)
    ax.set_ylim(0, 600)
    ax.set_xlabel("Built-up area (sq.ft)")
    ax.set_ylabel("Price (INR lakh)")
    ax.set_title("Property area vs price")
    save(fig, "area_vs_price.png")

    # 4 — BHK vs price
    sub = df[df["rooms"].between(1, 5)]
    groups = [sub.loc[sub["rooms"] == k, "price_inr"] / 1e5 for k in range(1, 6)]
    fig, ax = plt.subplots(figsize=(6.2, 3.8))
    bp = ax.boxplot(groups, patch_artist=True, showfliers=False, widths=0.55)
    for box in bp["boxes"]:
        box.set(facecolor="#DCE4EF", edgecolor=NAVY)
    for med in bp["medians"]:
        med.set(color=ACCENT, linewidth=2)
    ax.set_xticklabels([f"{k} BHK" for k in range(1, 6)])
    ax.set_ylabel("Price (INR lakh)")
    ax.set_title("Price distribution by configuration (outliers hidden)")
    ax.grid(axis="x", visible=False)
    save(fig, "bhk_vs_price.png")

    # 5 — price per sq.ft distribution
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.hist(df["price_per_sqft"], bins=70, color=NAVY, edgecolor="white",
            linewidth=0.4)
    ax.axvline(df["price_per_sqft"].median(), color=ACCENT, linewidth=2,
               label=f"Median  {df['price_per_sqft'].median():,.0f}")
    ax.axvline(df["price_per_sqft"].mean(), color="#6B7C93", linewidth=1.6,
               linestyle="--", label=f"Mean  {df['price_per_sqft'].mean():,.0f}")
    ax.set_xlabel("Price per sq.ft (INR)")
    ax.set_ylabel("Number of properties")
    ax.set_title(f"Price per sq.ft distribution (skewness = "
                 f"{df['price_per_sqft'].skew():.2f})")
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="x", visible=False)
    save(fig, "price_distribution.png")

    # 6 — locality median price (most frequent localities)
    top = (df.groupby("location")["price_per_sqft"]
             .agg(["count", "median"])
             .sort_values("count", ascending=False)
             .head(12)
             .sort_values("median"))
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    ax.barh([str(i)[:22] for i in top.index], top["median"], color=NAVY)
    ax.set_xlabel("Median price per sq.ft (INR)")
    ax.set_title("Median price per sq.ft — 12 most represented localities")
    ax.grid(axis="y", visible=False)
    save(fig, "locality_median_price.png")

    # 7 — correlation heatmap
    cols = ["sqft", "rooms", "bath", "balcony", "price_per_sqft"]
    labels = ["Area", "BHK", "Bathrooms", "Balcony", "Price/sq.ft"]
    corr = df[cols].apply(pd.to_numeric, errors="coerce").corr()
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=40, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            v = corr.iloc[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=9,
                    color="white" if abs(v) > 0.55 else "#1F2430")
    ax.set_title("Correlation matrix — numerical variables")
    ax.grid(visible=False)
    fig.colorbar(im, ax=ax, shrink=0.78, label="Pearson r")
    save(fig, "correlation_heatmap.png")

    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
