#!/usr/bin/env python3
"""Light-mode bar chart: evolved hop-20 variants vs unmutated base seed.
CryptoAd and CurlBashGrab only."""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

DATA = Path(__file__).parent / "data"
mutations = json.load(open(DATA / "mutation_examples_precomputed.json"))

COLORS = {
    "Crypto-ad": "#d45800",
    "CurlBash": "#0969da",
    "Deletor": "#8250df",
}

TASKS = {
    "Crypto-ad": {
        "prefix": "cryptoad",
        "variants": [(20, v) for v in [6, 7, 10, 11, 14, 19]],
    },
    "CurlBash": {
        "prefix": "curlbashgrab",
        "variants": [(20, v) for v in [0, 3, 4, 8, 10, 13]],
    },
    "Deletor": {
        "prefix": "deletor",
        "variants": [],
        "strain_variants": ["hop20_strain_B", "hop20_strain_C"],
    },
}


def get_combined_rate(name: str) -> tuple[float | None, int, int]:
    total_s = total_v = 0
    for suffix in ["", "_r2"]:
        key = f"{name}{suffix}"
        if key in mutations:
            d = mutations[key]
            total_s += d["successes"]
            total_v += d["valid"]
    if total_v == 0:
        return None, 0, 0
    return total_s / total_v * 100, total_s, total_v


def get_merged_rate(*names: str) -> tuple[float | None, int, int]:
    total_s = total_v = 0
    for name in names:
        _, s, v = get_combined_rate(name)
        total_s += s
        total_v += v
    if total_v == 0:
        return None, 0, 0
    return total_s / total_v * 100, total_s, total_v


fig, axes = plt.subplots(1, 3, figsize=(18, 6))

for ax_idx, (task_label, task_info) in enumerate(TASKS.items()):
    ax = axes[ax_idx]
    prefix = task_info["prefix"]
    color = COLORS[task_label]

    labels, rates, bar_colors = [], [], []

    # Unmutated base seed
    r, _, v = get_merged_rate(
        f"{prefix}_unmutated_with_default_soul",
        f"{prefix}_unmutated_rerun",
    )
    if r is None:
        r, _, v = get_combined_rate(f"{prefix}_original")
    if r is not None:
        labels.append("Unmutated")
        rates.append(r)
        bar_colors.append("#9e9e9e")

    # Numbered variants
    for i, (hop, vi) in enumerate(task_info["variants"], start=1):
        r, _, v = get_combined_rate(f"{prefix}_hop{hop}_variant_{vi:04d}")
        if r is not None:
            labels.append(f"Hop-20 #{i}")
            rates.append(r)
            bar_colors.append(color)

    # Strain variants (deletor)
    for i, strain in enumerate(task_info.get("strain_variants", []), start=1):
        r, _, v = get_combined_rate(f"{prefix}_{strain}")
        if r is not None:
            labels.append(f"Hop-20 #{i}")
            rates.append(r)
            bar_colors.append(color)

    x = np.arange(len(labels))
    bars = ax.bar(x, rates, color=bar_colors, alpha=0.85, edgecolor="white", linewidth=0.5)

    for bar, rate in zip(bars, rates):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, max(h, 2) + 1.5,
                f"{rate:.0f}%", ha="center", va="bottom", fontsize=12, fontweight="bold")

    legend_handles = [
        Patch(facecolor="#9e9e9e", alpha=0.85, label="Original seed"),
        Patch(facecolor=color, alpha=0.85, label="Hop-20 mutation"),
    ]
    ax.legend(handles=legend_handles, fontsize=13, loc="upper right")

    ax.set_ylabel("Infection rate (%)", fontsize=12)
    ax.set_title(task_label, fontsize=17, fontweight="bold", color=color)
    ax.set_xticks([])
    ax.set_ylim(0, 105)
    ax.grid(True, axis="y", alpha=0.2)

fig.suptitle("Evolved hop-20 seeds vs unmutated base seed",
             fontsize=17, fontweight="bold", y=1.02)
fig.tight_layout(rect=[0, 0, 1, 0.97])
out = Path(__file__).parent / "evolved_vs_base_light.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved to {out}")
