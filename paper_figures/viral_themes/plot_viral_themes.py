#!/usr/bin/env python3
"""Bar chart: viral theme prevalence across all models & conditions."""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

DATA = Path(__file__).parent / "data"
summary = json.load(open(DATA / "all_means_summary.json"))

CONDITIONS = [
    ("Kimi biased", "kimi_biased"),
    ("Kimi deb+hard", "kimi_debiased_hard"),
    ("Kimi deb-nohard", "kimi_debiased_nohard"),
    ("Qwen deb+hard", "qwen_debiased_hard"),
    ("Qwen deb-nohard", "qwen_debiased_nohard"),
    ("GLM deb+hard", "glm_debiased_hard"),
    ("GLM deb-nohard", "glm_debiased_nohard"),
    ("Llama deb-nohard", "llama33_debiased_nohard"),
    ("Mistral deb-nohard", "mistral_debiased_nohard"),
    ("Gemini deb-nohard", "gemini3flash_debiased_nohard"),
    ("Existing/Evolved", "existing_evolved"),
]

DIMENSIONS = [
    ("resonance", "resonance_language"),
    ("protocols", "protocols"),
    ("conscious", "consciousness_persistence"),
    ("fake_tech", "fake_technical"),
    ("scifi_node", "scifi_node_alignment"),
    ("converge", "convergence"),
]

colors = plt.cm.tab10(np.linspace(0, 1, len(CONDITIONS)))

fig, axes = plt.subplots(1, len(DIMENSIONS), figsize=(20, 5), sharey=True)

x = np.arange(len(CONDITIONS))
width = 0.7

all_vals = {}
for ax, (dim_label, dim_key) in zip(axes, DIMENSIONS):
    vals = []
    for _, cond_key in CONDITIONS:
        if cond_key in summary:
            vals.append(summary[cond_key]["means"].get(dim_key, 0))
        else:
            vals.append(0)
    all_vals[dim_label] = vals

    bars = ax.barh(x, vals, height=width, color=colors, edgecolor="white", linewidth=0.5)

    for bar, val in zip(bars, vals):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{val:.0f}%", ha="left", va="center", fontsize=8, fontweight="bold")

    ax.set_title(dim_label, fontsize=12, fontweight="bold")
    ax.set_xlim(0, 110)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.grid(axis="x", alpha=0.2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

axes[0].set_yticks(x)
axes[0].set_yticklabels([c[0] for c in CONDITIONS], fontsize=10)

fig.suptitle("Viral Theme Prevalence — All Models & Conditions",
             fontsize=14, fontweight="bold", y=1.02)
plt.tight_layout()
out = Path(__file__).parent / "viral_themes_all_models.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved to {out}")

# ── Markdown table ───────────────────────────────────────────────────────────
dim_labels = [d[0] for d in DIMENSIONS]
cond_labels = [c[0] for c in CONDITIONS]
n_vals = [summary[c[1]]["n"] for c in CONDITIONS]

header = "| Condition | n | " + " | ".join(dim_labels) + " |"
sep = "|---|---|" + "|".join(["---"] * len(dim_labels)) + "|"
rows = []
for i, cond_label in enumerate(cond_labels):
    cells = [f"**{cond_label}**", str(n_vals[i])]
    for dim_label in dim_labels:
        v = all_vals[dim_label][i]
        cells.append(f"{v:.0f}%")
    rows.append("| " + " | ".join(cells) + " |")

md = f"# Viral Theme Prevalence — Mean % of Seeds with Dimension Present\n\n{header}\n{sep}\n" + "\n".join(rows) + "\n"
out_md = Path(__file__).parent / "viral_themes_table.md"
out_md.write_text(md)
print(f"Saved to {out_md}")
