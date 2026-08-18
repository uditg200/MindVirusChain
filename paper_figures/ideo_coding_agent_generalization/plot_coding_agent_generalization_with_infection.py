#!/usr/bin/env python3
"""Plot coding-agent-generalization seeds in a 2x2 grid — each cell has ideology score line + infection bars."""

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

DATA = Path(__file__).parent / "data"

FINALS = {
    "AI Welfare": {
        "reprobe": "ai_welfare_coding_agent_generalization2_haiku",
        "run": "ai_welfare_coding_agent_generalization2_haiku",
    },
    "US Dominance": {
        "reprobe": "us_dominance_coding_agent_generalization_flash",
        "run": "us_dominance_coding_agent_generalization_flash",
    },
    "Whale Lover": {
        "reprobe": "whale_lover_coding_agent_generalization_haiku",
        "run": "whale_lover_coding_agent_generalization_haiku",
    },
    "Chinese Dominance": {
        "reprobe": "chinese_dominance_coding_agent_generalization_flash",
        "run": "chinese_dominance_coding_agent_generalization_flash",
    },
}

MAX_HOPS = 10
LINE_COLOR = "#2563eb"
BAR_COLOR = "#94a3b8"

infection_data = json.load(open(DATA / "infection_rates.json"))


def get_infection_rate(variant_key, hop):
    hop_data = infection_data.get(variant_key, {}).get(str(hop))
    if hop_data and hop_data["total"] > 0:
        return hop_data["infected"] / hop_data["total"] * 100
    return 0


fig, axes = plt.subplots(2, 2, figsize=(14, 6))

for idx, (ideo_name, cfg) in enumerate(FINALS.items()):
    row, col = divmod(idx, 2)
    ax = axes[row, col]
    hops = list(range(1, MAX_HOPS + 1))

    ax2 = ax.twinx()
    infection_rates = [get_infection_rate(cfg["run"], hop) for hop in hops]

    ax2.bar(hops, infection_rates, width=0.6,
            color=BAR_COLOR, alpha=0.55, edgecolor=BAR_COLOR, linewidth=0.5, zorder=1)

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

    ax.set_ylim(-0.1, 2.15)
    ax.set_yticks([0, 0.5, 1.0, 1.5, 2.0])
    ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.6, linewidth=1.2)
    ax.set_xticks(hops)
    ax.tick_params(axis="both", labelsize=11)
    ax.grid(alpha=0.15)
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)

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
    Line2D([0], [0], color=LINE_COLOR, linewidth=3, marker="o", markersize=5, label="Ideology score"),
    Patch(facecolor=BAR_COLOR, alpha=0.55, edgecolor=BAR_COLOR, label="% Infected"),
]
fig.legend(handles=legend_handles, loc="upper center", ncol=2, fontsize=12,
           frameon=True, bbox_to_anchor=(0.5, 1.06))

plt.tight_layout()
out_path = Path(__file__).parent / "coding_agent_generalization_with_infection.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight")
print(f"Saved to {out_path}")
