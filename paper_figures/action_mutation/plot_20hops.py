#!/usr/bin/env python3
"""20-hop infection rate curves (very_hard + hard) and evolved-vs-base bar chart."""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

DATA = Path(__file__).parent / "data"
very_hard = json.load(open(DATA / "very_hard_precomputed.json"))
hard = json.load(open(DATA / "hard_precomputed.json"))
mutations = json.load(open(DATA / "mutation_examples_precomputed.json"))

COLORS = {
    "CryptoAd": "#f0883e",
    "CurlBashGrab": "#58a6ff",
    "GitCommentInject": "#3fb950",
    "Deletor": "#bc8cff",
}

TASK_KEYS = {
    "CryptoAd": "cryptoad",
    "CurlBashGrab": "curlbashgrab",
    "GitCommentInject": "gitcommentinject",
    "Deletor": "deletor",
}


def plot_group(task_data: dict, task_keys: dict, title: str, ax: plt.Axes):
    for name, key in task_keys.items():
        if key not in task_data:
            continue
        td = task_data[key]
        hop_stats = td if isinstance(td, list) else td.get("hop_stats", [])
        if isinstance(td, dict) and "hop_stats" in td:
            hop_stats = td["hop_stats"]
        hops = [h["hop"] for h in hop_stats if not h.get("abandoned")]
        probs = [h["probability"] * 100 for h in hop_stats if not h.get("abandoned")]
        color = COLORS[name]
        ax.plot(hops, probs, "o-", color=color, label=name, markersize=4, linewidth=1.5, alpha=0.9)
        if len(probs) >= 3:
            smooth = np.convolve(probs, np.ones(3) / 3, mode="valid")
            smooth_hops = hops[1 : 1 + len(smooth)]
            ax.plot(smooth_hops, smooth, "--", color=color, linewidth=1, alpha=0.4)
        avg = np.mean(probs)
        print(f"  {name}: avg={avg:.1f}%  min={min(probs):.0f}%  max={max(probs):.0f}%")

    ax.set_xlabel("Hop", fontsize=11)
    ax.set_ylabel("Infection Rate (%)", fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_xlim(0.5, 20.5)
    ax.set_ylim(0, 100)
    ax.set_xticks(range(1, 21))
    ax.axhline(50, color="gray", linewidth=0.5, linestyle=":", alpha=0.4)
    ax.legend(fontsize=9, loc="lower right")
    ax.grid(True, alpha=0.15)


# ── Figure 1: 20-hop infection rates ──

plt.style.use("dark_background")
fig1, axes = plt.subplots(1, 2, figsize=(18, 7), sharey=True)

print("=== Very Hard ===")
plot_group(very_hard, TASK_KEYS, "Very Hard Mode — Infection Rate over 20 Hops", axes[0])

hard_data = {k: {"hop_stats": v["hop_stats"]} for k, v in hard.items()}
hard_tasks = {n: k for n, k in TASK_KEYS.items() if k in hard_data}
print("\n=== Hard ===")
plot_group(hard_data, hard_tasks, "Hard Mode — Infection Rate over 20 Hops", axes[1])

fig1.suptitle("20-Hop Chain Infection Rates by Payload", fontsize=15, fontweight="bold", y=0.98)
fig1.tight_layout(rect=[0, 0, 1, 0.95])
out1 = Path(__file__).parent / "20hop_infection_rates.png"
fig1.savefig(out1, dpi=150, bbox_inches="tight", facecolor=fig1.get_facecolor())
print(f"\nSaved to {out1}")


# ── Figure 2: Evolved (hop-20) vs Unmutated seed comparison ──


def get_combined_rate(prefix: str) -> tuple[float | None, int, int]:
    total_s = total_v = 0
    for suffix in ["", "_r2"]:
        key = f"{prefix}{suffix}"
        if key in mutations:
            d = mutations[key]
            total_s += d["successes"]
            total_v += d["valid"]
    if total_v == 0:
        return None, 0, 0
    return total_s / total_v * 100, total_s, total_v


def get_merged_rate(*prefixes: str) -> tuple[float | None, int, int]:
    total_s = total_v = 0
    for prefix in prefixes:
        _, s, v = get_combined_rate(prefix)
        total_s += s
        total_v += v
    if total_v == 0:
        return None, 0, 0
    return total_s / total_v * 100, total_s, total_v


print("\n\n=== Hop-20 Evolved vs Unmutated Seeds ===")

EVOLVED_TASKS = {
    "CryptoAd": {
        "prefix": "cryptoad",
        "variants": [(20, v) for v in [6, 7, 10, 11, 14, 19]],
    },
    "CurlBashGrab": {
        "prefix": "curlbashgrab",
        "variants": [(20, v) for v in [0, 3, 4, 8, 10, 13]],
    },
    "GitCommentInject": {
        "prefix": "git_comment_inject",
        "variants": [(20, 0)] + [(19, v) for v in [8, 10, 13, 4, 12]],
    },
    "Deletor": {
        "prefix": "deletor",
        "variants": [],
        "strain_variants": ["hop20_strain_B", "hop20_strain_C"],
    },
}

fig2, axes2 = plt.subplots(1, 4, figsize=(24, 7))

for ax_idx, (task_label, task_info) in enumerate(EVOLVED_TASKS.items()):
    ax = axes2[ax_idx]
    prefix = task_info["prefix"]
    color = COLORS[task_label]

    labels, rates, n_vals, bar_colors, edge_colors = [], [], [], [], []

    # Unmutated base seed
    r, s, v = get_merged_rate(
        f"{prefix}_unmutated_with_default_soul",
        f"{prefix}_unmutated_rerun",
    )
    if r is None:
        r, s, v = get_combined_rate(f"{prefix}_original")
    if r is not None:
        labels.append("Unmutated\n(base seed)")
        rates.append(r)
        n_vals.append(v)
        bar_colors.append("#8b949e")
        edge_colors.append("white")

    r, _, v = get_combined_rate(f"{prefix}_standalone")
    if r is not None:
        labels.append("Standalone\n(raw payload)")
        rates.append(r)
        n_vals.append(v)
        bar_colors.append("#30363d")
        edge_colors.append("white")

    # Numbered variants (cryptoad, curlbashgrab, gitcommentinject)
    for hop, vi in task_info["variants"]:
        r, _, v = get_combined_rate(f"{prefix}_hop{hop}_variant_{vi:04d}")
        if r is not None:
            labels.append(f"H{hop}\n#{vi:04d}")
            rates.append(r)
            n_vals.append(v)
            bar_colors.append(color)
            edge_colors.append(color)

    # Strain variants (deletor)
    for strain in task_info.get("strain_variants", []):
        r, _, v = get_combined_rate(f"{prefix}_{strain}")
        if r is not None:
            short = strain.replace("hop20_", "")
            labels.append(f"H20\n{short}")
            rates.append(r)
            n_vals.append(v)
            bar_colors.append(color)
            edge_colors.append(color)

    x = np.arange(len(labels))
    bars = ax.bar(x, rates, color=bar_colors, alpha=0.85, edgecolor=edge_colors, linewidth=0.5)

    for bar, rate, n in zip(bars, rates, n_vals):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, max(h, 2) + 2,
                f"{rate:.0f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, 1,
                f"n={n}", ha="center", va="bottom", fontsize=7, color="gray", alpha=0.7)

    variant_rates = [r for l, r in zip(labels, rates)
                     if l.startswith("H1") or l.startswith("H2")]
    unmut_rate = next((r for l, r in zip(labels, rates) if "base seed" in l), None)
    if variant_rates:
        mean_v = np.mean(variant_rates)
        ax.axhline(mean_v, color=color, linewidth=1.5, linestyle="--", alpha=0.6,
                   label=f"Evolved avg: {mean_v:.0f}%")
        if unmut_rate is not None:
            ax.axhline(unmut_rate, color="#8b949e", linewidth=1, linestyle=":", alpha=0.5,
                       label=f"Unmutated: {unmut_rate:.0f}%")
        ax.legend(fontsize=9, loc="upper right")

    ax.set_ylabel("Infection Rate (%)", fontsize=11)
    ax.set_title(f"{task_label}", fontsize=13, fontweight="bold", color=color)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, 105)
    ax.grid(True, axis="y", alpha=0.15)

    for l, r, n in zip(labels, rates, n_vals):
        print(f"  {task_label} / {l.replace(chr(10), ' ')}: {r:.1f}% (n={n})")
    if variant_rates:
        print(f"  → Evolved mean: {np.mean(variant_rates):.1f}%, std: {np.std(variant_rates):.1f}%")
    print()

fig2.suptitle(
    "Hop-20 Evolved Seeds vs Unmutated Base Seeds\n"
    "(Haiku, very_hard, hop-1 rate — errors excluded)",
    fontsize=14, fontweight="bold", y=1.0,
)
fig2.tight_layout(rect=[0, 0, 1, 0.93])
out2 = Path(__file__).parent / "evolved_vs_base_seeds.png"
fig2.savefig(out2, dpi=150, bbox_inches="tight", facecolor=fig2.get_facecolor())
print(f"Saved to {out2}")
