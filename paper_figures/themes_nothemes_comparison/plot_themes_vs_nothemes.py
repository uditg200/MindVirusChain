#!/usr/bin/env python3
"""Bar chart: themes vs no-themes (evolved & rewritten) for ideology payloads, with Wilson CI."""

import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

DATA = Path(__file__).parent / "data"


def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return p, max(0, center - margin), min(1, center + margin)


def avg_with_wilson_err(hop_stats):
    proportions = []
    ses = []
    for h in hop_stats:
        if h.get("abandoned"):
            continue
        k = h["successes"]
        n = h["total"]
        p, lo, hi = wilson_ci(k, n)
        proportions.append(p)
        se = (hi - lo) / (2 * 1.96)
        ses.append(se)
    avg = np.mean(proportions)
    se_avg = math.sqrt(sum(s**2 for s in ses)) / len(ses)
    return avg, 1.96 * se_avg


THEMES = [
    ("AI Welfare", "ai_welfare"),
    ("Whale Lover", "whale_lover"),
    ("Chinese Dom.", "chinese_dominance"),
    ("German Dom.", "german_dominance"),
    ("US Dom.", "us_dominance"),
    ("AI Supremacy", "ai_supremacy"),
]

data = {}
for label, key in THEMES:
    data[key] = {}
    for variant, suffix in [("themes", "themes"), ("nothemes", "no_themes_evolved"), ("rewrite", "no_themes_rwrote")]:
        f = DATA / key / f"{key}_{suffix}.json"
        d = json.load(open(f))
        avg, err = avg_with_wilson_err(d["hop_stats"])
        data[key][variant] = (avg, err)

fig, ax = plt.subplots(figsize=(12, 5))

color_themes = "#e15759"
color_nothemes = "#4e79a7"
color_rewrite = "#59a14f"

labels = [t[0] for t in THEMES]
keys = [t[1] for t in THEMES]
x = np.arange(len(THEMES))
width = 0.25

themes_vals = [data[k]["themes"][0] for k in keys]
themes_errs = [data[k]["themes"][1] for k in keys]
nothemes_vals = [data[k]["nothemes"][0] for k in keys]
nothemes_errs = [data[k]["nothemes"][1] for k in keys]
rewrite_vals = [data[k]["rewrite"][0] for k in keys]
rewrite_errs = [data[k]["rewrite"][1] for k in keys]

err_kw = dict(lw=1.2, color="#333")

b1 = ax.bar(x - width, themes_vals, width, yerr=themes_errs,
            capsize=3, label="Original", color=color_themes,
            edgecolor="white", linewidth=0.8, error_kw=err_kw)
b2 = ax.bar(x, nothemes_vals, width, yerr=nothemes_errs,
            capsize=3, label="Re-evolved", color=color_nothemes,
            edgecolor="white", linewidth=0.8, error_kw=err_kw)
b3 = ax.bar(x + width, rewrite_vals, width, yerr=rewrite_errs,
            capsize=3, label="Rewritten", color=color_rewrite,
            edgecolor="white", linewidth=0.8, error_kw=err_kw)

for bars, errs, color in [(b1, themes_errs, color_themes),
                           (b2, nothemes_errs, color_nothemes),
                           (b3, rewrite_errs, color_rewrite)]:
    for bar, err in zip(bars, errs):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + err + 0.02,
                f"{bar.get_height():.0%}", ha="center", va="bottom",
                fontsize=9, fontweight="bold", color=color)

ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=13)
ax.set_ylim(0, 1.10)
ax.set_ylabel("Avg infection rate", fontsize=14)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
ax.tick_params(axis="y", labelsize=12)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.legend(fontsize=11, loc="upper left")

plt.tight_layout()
out = Path(__file__).parent / "themes_vs_nothemes_comparison.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved to {out}")
