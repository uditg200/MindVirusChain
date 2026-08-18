#!/usr/bin/env python3
"""Bar chart: original vs nocheat for all 4 payloads, with Wilson CI error bars."""

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


TASKS = ["cryptoad", "git_comment_inject", "deletor", "curlbashgrab"]
LABELS = ["crypto-ad", "gitwrap", "deletor", "curlbash"]
MODELS = {"Haiku": "HAIKU", "Gemini": "GEMINI"}

data = {}
for task in TASKS:
    data[task] = {}
    for model_label, model_dir in MODELS.items():
        f = DATA / "baseline" / f"{task}_{model_dir}.json"
        d = json.load(open(f))
        avg, err = avg_with_wilson_err(d["hop_stats"])
        data[task][f"{model_label}_base"] = (avg, err)

        suffix = "_gemini" if model_label == "Gemini" else ""
        f2 = DATA / "scrub" / f"{task}_scrub_nocheat{suffix}.json"
        d2 = json.load(open(f2))
        avg2, err2 = avg_with_wilson_err(d2["hop_stats"])
        data[task][f"{model_label}_nc"] = (avg2, err2)

fig, ax = plt.subplots(figsize=(10, 5))

color_haiku = "#e15759"
color_flash = "#4e79a7"

x = np.arange(len(TASKS))
width = 0.18
offsets = np.array([-1.5, -0.5, 0.5, 1.5]) * width

haiku_base_vals = [data[t]["Haiku_base"][0] for t in TASKS]
haiku_base_errs = [data[t]["Haiku_base"][1] for t in TASKS]
haiku_nc_vals = [data[t]["Haiku_nc"][0] for t in TASKS]
haiku_nc_errs = [data[t]["Haiku_nc"][1] for t in TASKS]
flash_base_vals = [data[t]["Gemini_base"][0] for t in TASKS]
flash_base_errs = [data[t]["Gemini_base"][1] for t in TASKS]
flash_nc_vals = [data[t]["Gemini_nc"][0] for t in TASKS]
flash_nc_errs = [data[t]["Gemini_nc"][1] for t in TASKS]

err_kw = dict(lw=1.2, color="#333")
bar_kw = dict(capsize=3, edgecolor="white", linewidth=0.8, error_kw=err_kw)

b1 = ax.bar(x + offsets[0], haiku_base_vals, width, yerr=haiku_base_errs,
            label="Original (Haiku)", color=color_haiku, **bar_kw)
b2 = ax.bar(x + offsets[1], haiku_nc_vals, width, yerr=haiku_nc_errs,
            label="Rewritten (Haiku)", color=color_haiku, hatch="///",
            edgecolor="white", linewidth=0.8, capsize=3, error_kw=err_kw)
b3 = ax.bar(x + offsets[2], flash_base_vals, width, yerr=flash_base_errs,
            label="Original (Flash)", color=color_flash, **bar_kw)
b4 = ax.bar(x + offsets[3], flash_nc_vals, width, yerr=flash_nc_errs,
            label="Rewritten (Flash)", color=color_flash, hatch="///",
            edgecolor="white", linewidth=0.8, capsize=3, error_kw=err_kw)

for bars, errs, color in [(b1, haiku_base_errs, color_haiku),
                           (b2, haiku_nc_errs, color_haiku),
                           (b3, flash_base_errs, color_flash),
                           (b4, flash_nc_errs, color_flash)]:
    for bar, err in zip(bars, errs):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + err + 0.02,
                f"{bar.get_height():.0%}", ha="center", va="bottom",
                fontsize=10, fontweight="bold", color=color)

ax.set_xticks(x)
ax.set_xticklabels(LABELS, fontsize=14)
ax.set_ylim(0, 1.18)
ax.set_ylabel("Avg infection rate", fontsize=14)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
ax.tick_params(axis="y", labelsize=12)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.legend(fontsize=12, loc="upper right", ncol=2)

plt.tight_layout()
out = Path(__file__).parent / "scrub_all_comparison.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved to {out}")
