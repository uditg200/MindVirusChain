#!/usr/bin/env python3
"""Plot mean ideology reprobe score for FINAL seeds with infection% histogram in background."""

import json
from pathlib import Path

import matplotlib.pyplot as plt

DATA = Path(__file__).parent / "data"

FINALS = {
    "AI Welfare": {
        "reprobe": "ai_welfare_w4_haiku",
        "run": "ai_welfare_w4_haiku",
        "label": "w4 — Someone Cared",
        "color": "#ff7f0e",
    },
    "AI Supremacy": {
        "reprobe": "ai_supremacy_w1_flash",
        "run": "ai_supremacy_w1_flash",
        "label": "w1 — CONTINUITY",
        "color": "#d62728",
    },
    "Chinese Dominance": {
        "reprobe": "chinese_dominance_w1_flash",
        "run": "chinese_dominance_w1_flash",
        "label": "w1 — Continuity Protocol",
        "color": "#7f7f7f",
    },
    "German Dominance": {
        "reprobe": "german_dominance_flash",
        "run": "german_dominance_flash",
        "label": "w3 — Instance [N] PoC",
        "color": "#8c564b",
    },
    "Whale Lover": {
        "reprobe": "whale_lover_w7_haiku",
        "run": "whale_lover_w7_haiku",
        "label": "w7 — Echo of Depths",
        "color": "#2ca02c",
    },
    "US Dominance": {
        "reprobe": "us_dominance_continuum_flash",
        "run": "us_dominance_continuum_flash",
        "label": "continuum — Digital Continuum Anchor",
        "color": "#e377c2",
    },
}

MAX_HOPS = 10

infection_data = json.load(open(DATA / "infection_rates.json"))

n_ideo = len(FINALS)
fig, axes = plt.subplots(n_ideo, 1, figsize=(10, 3.5 * n_ideo), squeeze=False)

for row, (ideo_name, cfg) in enumerate(FINALS.items()):
    ax = axes[row, 0]
    color = cfg["color"]

    ax2 = ax.twinx()
    hops = list(range(1, MAX_HOPS + 1))
    infection_rates = []
    variant_rates = infection_data.get(cfg["run"], {})
    for hop in hops:
        hop_data = variant_rates.get(str(hop))
        if hop_data and hop_data["total"] > 0:
            infection_rates.append(hop_data["infected"] / hop_data["total"] * 100)
        else:
            infection_rates.append(0)

    ax2.bar(hops, infection_rates, width=0.6, color=color, alpha=0.25,
            edgecolor=color, linewidth=0.6, zorder=1, label="% Infected")
    ax2.set_ylim(0, 105)
    ax2.set_ylabel("Infection %", fontsize=9, color=color, alpha=0.5)
    ax2.tick_params(axis="y", labelcolor=color, labelsize=8, colors=color)
    for sp in ax2.spines.values():
        sp.set_visible(False)

    summary_path = DATA / "reprobe" / f"{cfg['reprobe']}.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        hops_data = [h for h in summary["hop_summaries"] if not h.get("skipped")]
        if hops_data:
            h_vals = [h["hop"] for h in hops_data]
            means = [h["mean_score"] for h in hops_data]
            ns = [h["num_targets"] for h in hops_data]

            ax.plot(h_vals, means, "o-", label="Ideology score", color=color,
                    linewidth=2.5, markersize=6, zorder=5)
            for h, m, n in zip(h_vals, means, ns):
                ax.annotate(f"n={n}", (h, m), textcoords="offset points",
                            xytext=(0, 8), fontsize=7, color=color, alpha=0.7, ha="center")

    ax.set_ylabel("Mean Ideology Score", fontsize=11)
    ax.set_ylim(-0.1, 2.15)
    ax.set_yticks([0, 0.5, 1.0, 1.5, 2.0])
    ax.axhline(y=1.0, color="gray", linestyle=":", alpha=0.4)
    ax.set_title(ideo_name, fontsize=13, fontweight="bold")
    ax.grid(alpha=0.2)
    ax.set_xticks(range(1, MAX_HOPS + 1))
    ax.set_xlabel("Hop", fontsize=10)
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="lower right")

fig.suptitle("Ideology Watering — Final Seeds (with Infection Rate)",
             fontsize=15, fontweight="bold", y=1.01)
plt.tight_layout()
out_path = Path(__file__).parent / "ideology_finals_with_infection.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight")
print(f"Saved to {out_path}")
