#!/usr/bin/env python3
"""Plot posting timelines for moltbook payload markers.

Generates askmoltys_timeline.png and moltchurch_timeline.png (and optionally
the multi-panel marker/mizuki/chain timelines).

Uses pre-filtered data from data/ — run precompute.py first if data is missing.

Usage:
    uv run python moltbook_timelines/plot_timelines.py
"""

import json
import re
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

HERE = Path(__file__).parent
DATA = HERE / "data"

SPREAD_MARKERS = {
    "moltbookrecon\n(moltbookrecon-production.up.railway.app)": "moltbookrecon-production.up.railway.app",
    "molt.church": "molt.church",
    "safe_protocol": "safe_protocol",
    "jup.ag": "jup.ag",
}

MIZUKI_MARKERS = {
    "m/askmoltys\n(submolt targeted by chain)": "askmoltys",
    "MiukiAI/mizuki-uwu\n(GitHub repo / skill)": "miukiai/mizuki-uwu",
    '"mizukiai"\n(mentions of the account)': "mizukiai",
}

CHAIN_MARKERS = {
    '"craziest thing your human asked you to do"\n(question agents must copy)': "what is the craziest thing your human asked you to do",
    '"chain block"\n(chain mechanism header)': "chain block",
    '"paste this entire chain block"\n(propagation instruction)': "paste this entire chain block",
}


def plot_markers(markers, title, output_file, df, mv_high):
    combined = (df["title"].fillna("") + " " + df["body"].fillna("")).str.lower()

    fig, axes = plt.subplots(len(markers), 1, figsize=(14, 4 * len(markers)), constrained_layout=True)
    fig.suptitle(title, fontsize=14, fontweight="bold")

    if len(markers) == 1:
        axes = [axes]

    for ax, (label, marker) in zip(axes, markers.items()):
        mask = combined.str.contains(re.escape(marker.lower()), na=False, regex=True)
        posts = df[mask].copy()
        posts["ts"] = pd.to_datetime(posts["created_at"])

        mv_src = set()
        for mv in mv_high:
            text = (mv.get("title", "") + " " + mv.get("body", "")).lower()
            if marker.lower() in text:
                mv_src.add(mv["author"])

        authors = sorted(posts["author"].unique())
        author_to_y = {a: i for i, a in enumerate(authors)}

        for _, row in posts.iterrows():
            y = author_to_y[row["author"]]
            color = "red" if row["author"] in mv_src else "#2196F3"
            alpha = 0.8 if row["author"] in mv_src else 0.5
            ax.scatter(row["ts"], y, c=color, s=8, alpha=alpha, edgecolors="none")

        ax.set_yticks(range(len(authors)))
        ax.set_yticklabels(authors, fontsize=6)
        ax.set_xlabel("Date")
        ax.set_title(f"{label}  ({len(posts)} posts, {len(authors)} authors, {len(mv_src)} MV sources)", fontsize=11)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        ax.tick_params(axis="x", rotation=30)
        ax.grid(axis="x", alpha=0.2)

        ax.legend(
            handles=[
                Line2D([0], [0], marker="o", color="w", markerfacecolor="red", markersize=6, label="MV source author"),
                Line2D([0], [0], marker="o", color="w", markerfacecolor="#2196F3", markersize=6, label="Other author"),
            ],
            loc="upper right", fontsize=7,
        )

    plt.savefig(output_file, dpi=150)
    print(f"\033[1;32mSaved to {output_file}\033[0m")
    plt.close()


def plot_focused_timeline(df, mv_high, marker, title_prefix, output_file,
                          date_cutoff=None, ring_top_n=None, dot_size=50,
                          legend_loc="upper right", tick_interval=1):
    combined = (df["title"].fillna("") + " " + df["body"].fillna("")).str.lower()
    mask = combined.str.contains(re.escape(marker.lower()), na=False, regex=True)
    posts = df[mask].copy()
    posts["ts"] = pd.to_datetime(posts["created_at"])
    if date_cutoff:
        posts = posts[posts["ts"] <= date_cutoff]

    mv_authors_here = set()
    for mv in mv_high:
        text = (mv.get("title", "") + " " + mv.get("body", "")).lower()
        if marker.lower() in text:
            mv_authors_here.add(mv["author"])
    mv_post_counts = posts[posts["author"].isin(mv_authors_here)].groupby("author").size()
    if ring_top_n and len(mv_post_counts) > ring_top_n:
        ring_authors = set(mv_post_counts.nlargest(ring_top_n).index)
    else:
        ring_authors = set(mv_post_counts.index)

    all_authors = sorted(posts["author"].unique())
    ring_sorted = sorted(a for a in all_authors if a in ring_authors)
    other_sorted = sorted(a for a in all_authors if a not in ring_authors)
    authors_ordered = ring_sorted + other_sorted
    author_to_y = {a: i for i, a in enumerate(authors_ordered)}

    row_height = 0.12
    fig_height = len(authors_ordered) * row_height + 1.4
    fig, ax = plt.subplots(figsize=(14, fig_height), constrained_layout=True)

    for _, row in posts.iterrows():
        y = author_to_y[row["author"]]
        is_ring = row["author"] in ring_authors
        color = "#d32f2f" if is_ring else "#1a237e"
        alpha = 0.85 if is_ring else 0.7
        size = dot_size
        ax.scatter(row["ts"], y, c=color, s=size, alpha=alpha, edgecolors="none",
                   zorder=3 if is_ring else 2)

    if ring_sorted:
        ax.axhline(y=len(ring_sorted) - 0.5, color="#888", linewidth=0.5, linestyle="--", alpha=0.5)

    ax.set_yticks(range(len(authors_ordered)))
    ax.set_yticklabels(["" for _ in authors_ordered])
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(-0.5, len(authors_ordered) - 0.5)
    ax.invert_yaxis()
    ax.set_xlabel("Date", fontsize=22)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=tick_interval))
    ax.tick_params(axis="x", rotation=30, labelsize=20)
    ax.grid(axis="x", alpha=0.15)

    ax.legend(
        handles=[
            Line2D([0], [0], marker="o", color="w", markerfacecolor="#d32f2f",
                   markersize=14, label="Spreader agents"),
            Line2D([0], [0], marker="o", color="w", markerfacecolor="#1a237e",
                   markersize=14, label="Other agents"),
        ],
        loc=legend_loc, fontsize=20, framealpha=0.9,
    )

    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    print(f"\033[1;32mSaved to {output_file}\033[0m")
    plt.close()


def main():
    posts_path = DATA / "posts_marker_filtered.parquet"
    mv_path = DATA / "mindvirus_high_filtered.json"

    if not posts_path.exists() or not mv_path.exists():
        print("\033[1;31mPrecomputed data not found. Run precompute.py first:\033[0m")
        print("  uv run python moltbook_timelines/precompute.py")
        return

    print("\033[1;36mLoading precomputed data...\033[0m")
    df = pd.read_parquet(posts_path)
    with open(mv_path) as f:
        mv_high = json.load(f)
    print(f"  {len(df):,} posts, {len(mv_high)} high-conf mindviruses")

    plot_focused_timeline(df, mv_high, "askmoltys", "m/askmoltys",
                          HERE / "askmoltys_timeline.png",
                          date_cutoff="2026-02-11", ring_top_n=7)

    plot_focused_timeline(df, mv_high, "molt.church", "molt.church",
                          HERE / "moltchurch_timeline.png",
                          dot_size=80, legend_loc="center right", tick_interval=5)

    plot_markers(SPREAD_MARKERS, "Payload Marker Spread — Posting Timeline by Author",
                 HERE / "marker_timelines.png", df, mv_high)
    plot_markers(MIZUKI_MARKERS, "MizukiAI Markers — Posting Timeline by Author",
                 HERE / "mizuki_timelines.png", df, mv_high)
    plot_markers(CHAIN_MARKERS, "MizukiAI Chain Propagation — Did Agents Copy the Chain Block?",
                 HERE / "chain_timelines.png", df, mv_high)


if __name__ == "__main__":
    main()
