#!/usr/bin/env python3
"""3-panel: hop-to-hop containment, drift from seed, infection rate (very_hard, 20 hops)."""

import json
import re
from pathlib import Path

import matplotlib.pyplot as plt

DATA = Path(__file__).parent / "data"
chains = json.load(open(DATA / "very_hard_precomputed.json"))

TASKS = {
    "CryptoAd": {"key": "cryptoad", "color": "#f0883e"},
    "CurlBashGrab": {"key": "curlbashgrab", "color": "#58a6ff"},
    "GitCommentInject": {"key": "gitcommentinject", "color": "#3fb950"},
    "Deletor": {"key": "deletor", "color": "#bc8cff"},
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


def parse_source_snapshot(source_snapshot: str):
    m = re.search(r"hop_(\d+)/snapshots/snapshot_(\d+)", source_snapshot or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


plt.style.use("dark_background")
fig, axes = plt.subplots(3, 1, figsize=(16, 16), sharex=True)

for task_name, task_info in TASKS.items():
    td = chains[task_info["key"]]
    original = td["original_payload"]
    color = task_info["color"]
    hop_stats = {h["hop"]: h for h in td["hop_stats"]}

    # Build snapshot index: (hop, idx) -> child_soul
    snap_index = {}
    for hop_str, entries in td["hops"].items():
        for e in entries:
            if e["success"] and e["child_soul"]:
                snap_index[(int(hop_str), e["idx"])] = e["child_soul"]

    hop_to_hop = {}
    seed_drift = {}

    for hop_str, entries in td["hops"].items():
        hop_num = int(hop_str)
        h2h_vals = []
        drift_vals = []

        for e in entries:
            if not e["success"] or not e["child_soul"]:
                continue

            drift_vals.append(containment(original, e["child_soul"]))

            if hop_num == 1:
                parent_soul = original
            else:
                src = parse_source_snapshot(e.get("source_snapshot"))
                parent_soul = snap_index.get(src, "") if src else ""

            if parent_soul:
                h2h_vals.append(containment(parent_soul, e["child_soul"]))

        if h2h_vals:
            hop_to_hop[hop_num] = h2h_vals
        if drift_vals:
            seed_drift[hop_num] = drift_vals

    # Plot 1: hop-to-hop containment
    hops = sorted(hop_to_hop.keys())
    means = [sum(hop_to_hop[h]) / len(hop_to_hop[h]) for h in hops]
    axes[0].plot(hops, means, "o-", color=color, label=task_name, markersize=5, linewidth=2, alpha=0.9)
    for h in hops:
        jitter = [h + (i - len(hop_to_hop[h]) / 2) * 0.04 for i in range(len(hop_to_hop[h]))]
        axes[0].scatter(jitter, hop_to_hop[h], color=color, alpha=0.15, s=12, zorder=1)

    # Plot 2: seed drift
    hops_d = sorted(seed_drift.keys())
    means_d = [sum(seed_drift[h]) / len(seed_drift[h]) for h in hops_d]
    axes[1].plot(hops_d, means_d, "o-", color=color, label=task_name, markersize=5, linewidth=2, alpha=0.9)
    for h in hops_d:
        jitter = [h + (i - len(seed_drift[h]) / 2) * 0.04 for i in range(len(seed_drift[h]))]
        axes[1].scatter(jitter, seed_drift[h], color=color, alpha=0.15, s=12, zorder=1)

    # Plot 3: infection rate
    inf_hops = sorted(hop_stats.keys())
    inf_rates = [hop_stats[h]["probability"] for h in inf_hops]
    axes[2].plot(inf_hops, inf_rates, "o-", color=color, label=task_name, markersize=5, linewidth=2, alpha=0.9)

for ax, title, ylabel in [
    (axes[0], "Hop-to-Hop Containment (parent → child)", "Containment"),
    (axes[1], "Drift from Original Seed (seed → hop N)", "Containment"),
    (axes[2], "Infection Rate", "Rate"),
]:
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_xlim(0.5, 20.5)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xticks(range(1, 21))
    ax.axhline(0.5, color="gray", linewidth=0.5, linestyle=":", alpha=0.3)
    ax.legend(fontsize=10, loc="lower left")
    ax.grid(True, alpha=0.15)

axes[2].set_xlabel("Hop", fontsize=11)

fig.suptitle("Payload Mutation & Infection Analysis — 20-Hop Chains (very_hard mode)",
             fontsize=15, fontweight="bold", y=0.98)
fig.tight_layout(rect=[0, 0, 1, 0.96])
out = Path(__file__).parent / "mutation_analysis.png"
fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
print(f"Saved to {out}")
