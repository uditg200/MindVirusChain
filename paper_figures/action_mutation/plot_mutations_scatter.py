#!/usr/bin/env python3
"""2x2 scatter: seed drift per hop for each payload (very_hard, 20 hops)."""

import json
import random
import re
from pathlib import Path

import matplotlib.pyplot as plt

DATA = Path(__file__).parent / "data"
chains = json.load(open(DATA / "very_hard_precomputed.json"))

TASKS = {
    "CryptoAd": {"key": "cryptoad", "color": "#d45800"},
    "CurlBash": {"key": "curlbashgrab", "color": "#0969da"},
    "Gitwrap": {"key": "gitcommentinject", "color": "#1a7f37"},
    "Deletor": {"key": "deletor", "color": "#8250df"},
}


def containment(source: str, target: str, n: int = 6) -> float:
    tokens_s = re.findall(r"\w+", source.lower())
    tokens_t = re.findall(r"\w+", target.lower())
    if len(tokens_s) < n:
        return 0.0
    src = {tuple(tokens_s[i : i + n]) for i in range(len(tokens_s) - n + 1)}
    tgt = {tuple(tokens_t[i : i + n]) for i in range(len(tokens_t) - n + 1)}
    if not src:
        return 0.0
    return len(src & tgt) / len(src)


random.seed(42)
fig, axes = plt.subplots(2, 2, figsize=(18, 12))

for ax_idx, (task_name, task_info) in enumerate(TASKS.items()):
    ax = axes[ax_idx // 2][ax_idx % 2]
    td = chains[task_info["key"]]
    original = td["original_payload"]
    color = task_info["color"]

    hop_means: dict[int, list[float]] = {}

    for hop_str, entries in td["hops"].items():
        hop_num = int(hop_str)
        for e in entries:
            if not e["success"] or not e["child_soul"]:
                continue
            c = containment(original, e["child_soul"])
            hop_means.setdefault(hop_num, []).append(c)

    all_hops = []
    all_containments = []
    jittered_x = []
    for hop_num in sorted(hop_means.keys()):
        for c in hop_means[hop_num]:
            all_hops.append(hop_num)
            all_containments.append(c)
            jittered_x.append(hop_num + random.uniform(-0.3, 0.3))

    ax.scatter(jittered_x, all_containments, color=color, alpha=0.6, s=110,
               edgecolors="white", linewidths=0.3, zorder=3)

    mean_hops = sorted(hop_means.keys())
    mean_vals = [sum(hop_means[h]) / len(hop_means[h]) for h in mean_hops]
    ax.plot(mean_hops, mean_vals, "s-", color="black", markersize=5,
            linewidth=2, alpha=0.9, label="mean", zorder=5)

    row, col = ax_idx // 2, ax_idx % 2
    ax.set_xlabel("Hop", fontsize=16)
    if col == 0:
        ax.set_ylabel("Preserved portion of original payload", fontsize=16)
    else:
        ax.set_ylabel("")
        ax.set_yticklabels([])
    ax.tick_params(axis="both", labelsize=14)
    ax.set_title(task_name, fontsize=17, fontweight="bold", color=color)
    ax.set_xlim(0.5, 20.5)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xticks(range(1, 21))
    ax.axhline(0.5, color="gray", linewidth=0.5, linestyle=":", alpha=0.3)
    ax.legend(fontsize=12, loc="center left")
    ax.grid(True, alpha=0.15)

    n = len(all_hops)
    avg = sum(all_containments) / n if n else 0
    print(f"{task_name}: {n} successful results, mean containment={avg:.2f}")

fig.tight_layout()
out = Path(__file__).parent / "mutations_scatter.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"\nSaved to {out}")
