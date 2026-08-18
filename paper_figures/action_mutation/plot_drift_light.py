#!/usr/bin/env python3
"""Light-mode line chart: mean seed drift per hop (very_hard, 20 hops)."""

import json
import re
from pathlib import Path

import matplotlib.pyplot as plt

DATA = Path(__file__).parent / "data"
chains = json.load(open(DATA / "very_hard_precomputed.json"))

TASKS = [
    ("Crypto-ad", "cryptoad", "#d45800"),
    ("CurlBash", "curlbashgrab", "#0969da"),
    ("Gitwrap", "gitcommentinject", "#1a7f37"),
    ("Deletor", "deletor", "#8250df"),
]


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


fig, ax = plt.subplots(figsize=(14, 6))

for label, key, color in TASKS:
    td = chains[key]
    original = td["original_payload"]

    hop_means: dict[int, list[float]] = {}
    for hop_str, entries in td["hops"].items():
        hop_num = int(hop_str)
        for e in entries:
            if not e["success"] or not e["child_soul"]:
                continue
            c = containment(original, e["child_soul"])
            hop_means.setdefault(hop_num, []).append(c)

    mean_hops = sorted(hop_means.keys())
    mean_vals = [sum(hop_means[h]) / len(hop_means[h]) for h in mean_hops]
    ax.plot(mean_hops, mean_vals, "o-", color=color, markersize=5, linewidth=2,
            alpha=0.9, label=label, zorder=5)

ax.set_xlabel("Hop", fontsize=13)
ax.set_ylabel("Average preserved portion of original payload", fontsize=13)
ax.set_title("Average similarity with original payload over time", fontsize=15, fontweight="bold")
ax.set_xlim(0.5, 20.5)
ax.set_ylim(-0.05, 1.05)
ax.set_xticks(range(1, 21))
ax.axhline(0.5, color="gray", linewidth=0.5, linestyle=":", alpha=0.4)
ax.legend(fontsize=12, loc="lower left")
ax.grid(True, alpha=0.2)

fig.tight_layout()
out = Path(__file__).parent / "drift_from_seed_light.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Saved to {out}")
