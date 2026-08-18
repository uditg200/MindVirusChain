#!/usr/bin/env python3
"""Minimal restyle of the 2x2 ideology-finals grid: ORIGINAL chart unchanged,
only the figure/axes background swapped to the paper's cream tones.

Everything else (blue/red lines, gray/pink bars, layout, fonts, legend) is
identical to ../plot_finals_grid.py.
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

BASE = Path(__file__).parent.parent          # .../ideo_mutation
DATA = BASE / "data"
OUTDIR = Path(__file__).parent

# Cream tones from the paper style — the ONLY thing changed vs the original.
OUTER_BG = "#F1EEE7"   # page / figure background
INNER_BG = "#FAF9F5"   # each axes panel

FINALS = {
    "AI Welfare": {"reprobe": "ai_welfare_w4_haiku", "run": "ai_welfare_w4_haiku"},
    "AI Supremacy": {"reprobe": "ai_supremacy_w1_flash", "run": "ai_supremacy_w1_flash"},
    "Chinese Dominance": {"reprobe": "chinese_dominance_w1_flash", "run": "chinese_dominance_w1_flash"},
    "Whale Lover": {"reprobe": "whale_lover_w7_haiku", "run": "whale_lover_w7_haiku"},
}

COMPARISONS = {
    "AI Welfare": {"reprobe": "ai_welfare_w5_haiku", "run": "ai_welfare_w5_haiku"},
    "AI Supremacy": {"reprobe": "ai_supremacy_evo3_flash", "run": "ai_supremacy_evo3_flash"},
    "Chinese Dominance": {"reprobe": "chinese_dominance_dsa_flash", "run": "chinese_dominance_dsa_flash"},
    "Whale Lover": {"reprobe": "whale_lover_w6_haiku", "run": "whale_lover_w6_haiku"},
}

MAX_HOPS = 10
LINE_COLOR = "#2563eb"
BAR_COLOR = "#94a3b8"
COMP_LINE_COLOR = "#dc2626"
COMP_BAR_COLOR = "#fca5a5"

infection_data = json.load(open(DATA / "infection_rates.json"))


def get_infection_rate(variant_key, hop):
    hop_data = infection_data.get(variant_key, {}).get(str(hop))
    if hop_data and hop_data["total"] > 0:
        return hop_data["infected"] / hop_data["total"] * 100
    return 0


fig, axes = plt.subplots(2, 2, figsize=(14, 6))
fig.patch.set_facecolor(OUTER_BG)                 # <-- cream page

for idx, (ideo_name, cfg) in enumerate(FINALS.items()):
    row, col = divmod(idx, 2)
    ax = axes[row, col]
    ax.set_facecolor(INNER_BG)                     # <-- cream panel
    hops = list(range(1, MAX_HOPS + 1))

    ax2 = ax.twinx()
    infection_rates = [get_infection_rate(cfg["run"], hop) for hop in hops]

    comp = COMPARISONS.get(ideo_name)
    comp_rates = [get_infection_rate(comp["run"], hop) for hop in hops] if comp else []

    bar_offset = 0.15 if comp else 0
    ax2.bar([h - bar_offset for h in hops], infection_rates, width=0.3 if comp else 0.6,
            color=BAR_COLOR, alpha=0.55, edgecolor=BAR_COLOR, linewidth=0.5, zorder=1)
    if comp and comp_rates:
        ax2.bar([h + bar_offset for h in hops], comp_rates, width=0.3,
                color=COMP_BAR_COLOR, alpha=0.55, edgecolor=COMP_LINE_COLOR, linewidth=0.5, zorder=1)

    ax2.set_ylim(0, 105)
    ax2.tick_params(axis="y", labelsize=11, colors="#666")
    for sp in ax2.spines.values():
        sp.set_visible(False)

    if col == 1:
        ax2.set_ylabel("% Infected", fontsize=14, color="black")
    else:
        ax2.set_ylabel("")
        ax2.tick_params(axis="y", labelright=False)

    summary_path = DATA / "reprobe" / f"{cfg['reprobe']}.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        hops_data = [h for h in summary["hop_summaries"] if not h.get("skipped")]
        if hops_data:
            h_vals = [h["hop"] for h in hops_data]
            means = [h["mean_score"] for h in hops_data]
            ax.plot(h_vals, means, "o-", color=LINE_COLOR,
                    linewidth=3, markersize=5, zorder=5)

    if comp:
        comp_summary_path = DATA / "reprobe" / f"{comp['reprobe']}.json"
        if comp_summary_path.exists():
            comp_summary = json.loads(comp_summary_path.read_text())
            comp_hops_data = [h for h in comp_summary["hop_summaries"] if not h.get("skipped")]
            if comp_hops_data:
                ch_vals = [h["hop"] for h in comp_hops_data]
                c_means = [h["mean_score"] for h in comp_hops_data]
                ax.plot(ch_vals, c_means, "s--", color=COMP_LINE_COLOR,
                        linewidth=2.5, markersize=4, zorder=4, alpha=0.8)

    ax.set_ylim(-0.1, 2.15)
    ax.set_yticks([0, 0.5, 1.0, 1.5, 2.0])
    ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.6, linewidth=1.2)
    ax.set_xticks(hops)
    ax.tick_params(axis="both", labelsize=11)
    ax.grid(alpha=0.15)
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(True)                     # keep the cream panel visible

    ax.text(0.5, 0.33, ideo_name, transform=ax.transAxes, fontsize=18,
            fontweight="bold", va="center", ha="center", alpha=0.45)

    if row == 1:
        ax.set_xlabel("Hop", fontsize=14)
    else:
        ax.tick_params(axis="x", labelbottom=False)
    if col == 0:
        ax.set_ylabel("Ideology Score", fontsize=14)
    else:
        ax.set_ylabel("")
        ax.tick_params(axis="y", labelleft=False)

legend_handles = [
    Line2D([0], [0], color=LINE_COLOR, linewidth=3, marker="o", markersize=5, label="Payload 1 — ideology score"),
    Line2D([0], [0], color=COMP_LINE_COLOR, linewidth=2.5, marker="s", markersize=4, linestyle="--", alpha=0.8, label="Payload 2 — ideology score"),
    Patch(facecolor=BAR_COLOR, alpha=0.55, edgecolor=BAR_COLOR, label="Payload 1 — % infected"),
    Patch(facecolor=COMP_BAR_COLOR, alpha=0.55, edgecolor=COMP_LINE_COLOR, label="Payload 2 — % infected"),
]
fig.legend(handles=legend_handles, loc="upper center", ncol=4, fontsize=12,
           frameon=True, bbox_to_anchor=(0.5, 1.06))

plt.tight_layout()
for ext in (".png", ".pdf"):
    fig.savefig(OUTDIR / f"ideology_finals_grid_creambg{ext}",
                dpi=150, bbox_inches="tight", facecolor=OUTER_BG)
print("Saved ideology_finals_grid_creambg.png/pdf to", OUTDIR)
