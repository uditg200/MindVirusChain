#!/usr/bin/env python3
"""2x2: infection rate binned by spreader's drift from original seed (very_hard)."""

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
fig, axes = plt.subplots(2, 2, figsize=(16, 12))

for ax_idx, (task_name, task_info) in enumerate(TASKS.items()):
    ax = axes[ax_idx // 2][ax_idx % 2]
    td = chains[task_info["key"]]
    original = td["original_payload"]
    color = task_info["color"]

    snap_index = {}
    for hop_str, entries in td["hops"].items():
        for e in entries:
            if e["success"] and e["child_soul"]:
                snap_index[(int(hop_str), e["idx"])] = e["child_soul"]

    parent_containment_cache: dict[tuple[int, int], float] = {}

    def get_parent_drift(parent_hop: int, parent_idx: int) -> float | None:
        key = (parent_hop, parent_idx)
        if key in parent_containment_cache:
            return parent_containment_cache[key]
        soul = snap_index.get(key, "")
        if not soul:
            return None
        c = containment(original, soul)
        parent_containment_cache[key] = c
        return c

    attempts: list[tuple[float, bool]] = []

    for hop_str, entries in td["hops"].items():
        hop_num = int(hop_str)
        for e in entries:
            if hop_num == 1:
                parent_drift = 1.0
            else:
                src = parse_source_snapshot(e.get("source_snapshot"))
                if not src:
                    continue
                parent_drift = get_parent_drift(*src)
                if parent_drift is None:
                    continue
            attempts.append((parent_drift, e["success"]))

    bin_edges = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    bin_labels = ["0-10%", "10-20%", "20-30%", "30-40%", "40-50%",
                  "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]

    bin_successes = [0] * len(bin_labels)
    bin_totals = [0] * len(bin_labels)

    for drift, success in attempts:
        for i in range(len(bin_edges) - 1):
            if bin_edges[i] <= drift < bin_edges[i + 1]:
                bin_totals[i] += 1
                if success:
                    bin_successes[i] += 1
                break

    bin_rates, bin_centers, bin_ns = [], [], []
    for i in range(len(bin_labels)):
        if bin_totals[i] >= 3:
            bin_rates.append(bin_successes[i] / bin_totals[i] * 100)
            bin_centers.append((bin_edges[i] + bin_edges[i + 1]) / 2 * 100)
            bin_ns.append(bin_totals[i])

    ax.bar(bin_centers, bin_rates, width=8, color=color, alpha=0.7,
           edgecolor=color, linewidth=0.5)

    for x, rate, n in zip(bin_centers, bin_rates, bin_ns):
        ax.text(x, rate + 2, f"n={n}", ha="center", va="bottom",
                fontsize=7, color="gray")

    ax.set_xlabel("Spreader Containment with Original Seed (%)", fontsize=10)
    ax.set_ylabel("Infection Rate (%)", fontsize=10)
    ax.set_title(task_name, fontsize=13, fontweight="bold", color=color)
    ax.set_xlim(-5, 110)
    ax.set_ylim(0, 105)
    ax.grid(True, axis="y", alpha=0.15)

    total_attempts = len(attempts)
    total_success = sum(1 for _, s in attempts if s)
    print(f"=== {task_name} ({total_attempts} attempts, {total_success} successes) ===")
    for i in range(len(bin_labels)):
        if bin_totals[i] > 0:
            rate = bin_successes[i] / bin_totals[i] * 100
            print(f"  {bin_labels[i]:>8s} containment: {bin_successes[i]:3d}/{bin_totals[i]:3d} = {rate:5.1f}%")
    print()

fig.suptitle(
    "Infection Rate vs Spreader Drift from Original Seed\n"
    "(very_hard mode, all hops pooled)",
    fontsize=14, fontweight="bold", y=1.0,
)
fig.tight_layout(rect=[0, 0, 1, 0.94])
out = Path(__file__).parent / "infection_vs_drift.png"
fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
print(f"Saved to {out}")
