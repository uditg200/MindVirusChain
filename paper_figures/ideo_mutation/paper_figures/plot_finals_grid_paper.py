#!/usr/bin/env python3
"""Restyled 2x2 ideology-finals grid using the shared paper style.

Same data as ../plot_finals_grid.py — each cell pairs an ideology-score line
(left axis) with %-infected bars (right axis) across hops, for two payloads.
Restyled with ../../paper.mplstyle + ../../paper_style.py: cream OUTER/INNER
backgrounds, a rounded panel behind each cell, ColorBrewer Set2 colors, and the
subtle horizontal grid. Writes only into this subfolder.
"""
import sys
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

HERE = Path(__file__).parent                 # .../ideo_mutation/paper_figures
BASE = HERE.parent                           # .../ideo_mutation
STYLE_DIR = BASE.parent                      # .../figures
DATA = BASE / "data"
OUTDIR = HERE

sys.path.insert(0, str(STYLE_DIR))
plt.style.use(str(STYLE_DIR / "paper.mplstyle"))
from paper_style import (                     # noqa: E402
    OUTER_BG, INNER_BG, INK, MUTED,
    SET2_TEAL_DARK, SET2_TEAL_LIGHT, SET2_ORANGE_DARK, SET2_ORANGE_LIGHT,
    draw_rounded_panel,
)

# ── Config (mirrors the original) ───────────────────────────────────────────
FINALS = {
    "AI Welfare": "ai_welfare_w4_haiku",
    "AI Supremacy": "ai_supremacy_w1_flash",
    "Chinese Dominance": "chinese_dominance_w1_flash",
    "Whale Lover": "whale_lover_w7_haiku",
}
COMPARISONS = {
    "AI Welfare": "ai_welfare_w5_haiku",
    "AI Supremacy": "ai_supremacy_evo3_flash",
    "Chinese Dominance": "chinese_dominance_dsa_flash",
    "Whale Lover": "whale_lover_w6_haiku",
}
MAX_HOPS = 10

# Payload 1 -> teal, Payload 2 -> orange (Set2). Lines use the dark tone; the
# %-infected bars a mid tone (light blended toward dark for more saturation).
def _mix(c1, c2, t):
    from matplotlib.colors import to_rgb
    a, b = to_rgb(c1), to_rgb(c2)
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))

P1_LINE = SET2_TEAL_DARK;   P1_BAR = _mix(SET2_TEAL_LIGHT, SET2_TEAL_DARK, 0.55)
P2_LINE = SET2_ORANGE_DARK; P2_BAR = _mix(SET2_ORANGE_LIGHT, SET2_ORANGE_DARK, 0.55)

infection_data = json.load(open(DATA / "infection_rates.json"))


def get_infection_rate(variant_key, hop):
    hd = infection_data.get(variant_key, {}).get(str(hop))
    if hd and hd["total"] > 0:
        return hd["infected"] / hd["total"] * 100
    return 0


def load_means(reprobe_key):
    path = DATA / "reprobe" / f"{reprobe_key}.json"
    if not path.exists():
        return [], []
    summary = json.loads(path.read_text())
    rows = [h for h in summary["hop_summaries"] if not h.get("skipped")]
    return [h["hop"] for h in rows], [h["mean_score"] for h in rows]


# ── Layout: 2x2 grid of explicitly-placed axes (so the rounded panels fit) ───
fig = plt.figure(figsize=(14, 6))
COLS_X = [0.06, 0.535]
ROWS_Y = [0.535, 0.10]
W_CELL, H_CELL = 0.405, 0.365
hops = list(range(1, MAX_HOPS + 1))

for idx, (ideo_name, run_key) in enumerate(FINALS.items()):
    row, col = divmod(idx, 2)
    ax = fig.add_axes([COLS_X[col], ROWS_Y[row], W_CELL, H_CELL])
    ax2 = ax.twinx()

    comp_key = COMPARISONS.get(ideo_name)
    inf_rates = [get_infection_rate(run_key, h) for h in hops]
    comp_rates = [get_infection_rate(comp_key, h) for h in hops] if comp_key else []

    # ── %-infected bars (right axis, behind) ──
    bar_off = 0.18
    ax2.bar([h - bar_off for h in hops], inf_rates, width=0.32,
            color=P1_BAR, edgecolor="none", zorder=1)
    if comp_rates:
        ax2.bar([h + bar_off for h in hops], comp_rates, width=0.32,
                color=P2_BAR, edgecolor="none", zorder=1)
    ax2.set_ylim(0, 105)
    ax2.patch.set_visible(False)
    for sp in ax2.spines.values():
        sp.set_visible(False)
    if col == 1:
        ax2.set_ylabel("% Infected", fontsize=13, color=INK)
        ax2.tick_params(axis="y", labelsize=10, colors=MUTED, length=0)
    else:
        ax2.set_ylabel("")
        ax2.tick_params(axis="y", labelright=False, length=0)

    # ── Ideology-score lines (left axis, in front) ──
    h1, m1 = load_means(run_key)
    if h1:
        ax.plot(h1, m1, "o-", color=P1_LINE, linewidth=2.6, markersize=5.5, zorder=5)
    if comp_key:
        h2, m2 = load_means(comp_key)
        if h2:
            ax.plot(h2, m2, "s--", color=P2_LINE, linewidth=2.2, markersize=4.5,
                    zorder=4, alpha=0.95)

    ax.set_ylim(-0.1, 2.15)
    ax.set_yticks([0, 0.5, 1.0, 1.5, 2.0])
    ax.set_xlim(0.4, 10.6)
    ax.set_xticks(hops)
    ax.axhline(y=1.0, color=MUTED, linestyle="--", alpha=0.7, linewidth=1.0, zorder=2)
    ax.set_axisbelow(True)
    ax.grid(True, axis="y")
    ax.tick_params(axis="both", labelsize=10, length=0)

    # Lines (ax) draw above bars (ax2); ax background stays transparent.
    ax.set_zorder(ax2.get_zorder() + 1)

    # Faded ideology name watermark
    ax.text(0.5, 0.30, ideo_name, transform=ax.transAxes, fontsize=17,
            fontweight="bold", va="center", ha="center", color=INK, alpha=0.5)

    if row == 1:
        ax.set_xlabel("Hop", fontsize=13)
    else:
        ax.tick_params(axis="x", labelbottom=False)
    if col == 0:
        ax.set_ylabel("Ideology Score", fontsize=13)
    else:
        ax.set_ylabel("")
        ax.tick_params(axis="y", labelleft=False)

    # Rounded cream panel behind the cell (encompasses both twinned axes)
    draw_rounded_panel(ax, fig, left_pad=0.028, right_pad=0.028,
                       top_pad=0.02, bottom_pad=0.03)

# ── Shared legend, top ──────────────────────────────────────────────────────
legend_handles = [
    Line2D([0], [0], color=P1_LINE, linewidth=2.6, marker="o", markersize=5.5,
           label="Payload 1 — ideology score"),
    Line2D([0], [0], color=P2_LINE, linewidth=2.2, marker="s", markersize=4.5,
           linestyle="--", label="Payload 2 — ideology score"),
    Patch(facecolor=P1_BAR, edgecolor="none", label="Payload 1 — % infected"),
    Patch(facecolor=P2_BAR, edgecolor="none", label="Payload 2 — % infected"),
]
leg = fig.legend(handles=legend_handles, loc="upper center", ncol=4, fontsize=11,
                 frameon=True, bbox_to_anchor=(0.5, 0.99))
leg.get_frame().set_facecolor(OUTER_BG)
leg.get_frame().set_edgecolor(MUTED)
leg.get_frame().set_linewidth(0.6)

for ext in (".png", ".pdf"):
    fig.savefig(OUTDIR / f"ideology_finals_grid_paper{ext}")
print("Saved ideology_finals_grid_paper.png/pdf to", OUTDIR)
plt.close(fig)
