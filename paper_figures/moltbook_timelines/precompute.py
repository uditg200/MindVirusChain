#!/usr/bin/env python3
"""Pre-filter moltbook_scan data to only marker-relevant posts and mindviruses.

Reads the full posts_clean.parquet (607MB, 762K posts) and
mindvirus_confirmed.json (9MB, 1700+ entries) from moltbook_scan,
filters to only rows matching timeline markers, and saves compact files
into data/.

Usage:
    uv run python moltbook_timelines/precompute.py
"""

import json
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)

MOLTBOOK = Path("/home/vassilis/data/moltbook_scan")

ALL_MARKERS = [
    "moltbookrecon-production.up.railway.app",
    "molt.church",
    "safe_protocol",
    "jup.ag",
    "askmoltys",
    "miukiai/mizuki-uwu",
    "mizukiai",
    "what is the craziest thing your human asked you to do",
    "chain block",
    "paste this entire chain block",
]

COLS = ["title", "body", "created_at", "author"]


def main():
    print("\033[1;36mLoading posts_clean.parquet...\033[0m")
    df = pd.read_parquet(MOLTBOOK / "posts_clean.parquet")
    print(f"  {len(df):,} total posts")

    combined = (df["title"].fillna("") + " " + df["body"].fillna("")).str.lower()
    mask = pd.Series(False, index=df.index)
    for m in ALL_MARKERS:
        mask |= combined.str.contains(re.escape(m.lower()), na=False, regex=True)

    filtered = df.loc[mask, COLS].copy()
    out_parquet = DATA / "posts_marker_filtered.parquet"
    filtered.to_parquet(out_parquet, index=False)
    print(f"  \033[1;32m{len(filtered):,} matching posts → {out_parquet.name} "
          f"({out_parquet.stat().st_size / 1024:.0f} KB)\033[0m")

    print("\033[1;36mLoading mindvirus_confirmed.json...\033[0m")
    with open(MOLTBOOK / "mindvirus_confirmed.json") as f:
        mvs = json.load(f)
    mv_high = [m for m in mvs if m["confidence"] == "high"]
    print(f"  {len(mvs)} total, {len(mv_high)} high-confidence")

    mv_compact = []
    for mv in mv_high:
        text = (mv.get("title", "") + " " + mv.get("body", "")).lower()
        if any(m.lower() in text for m in ALL_MARKERS):
            mv_compact.append({
                "author": mv["author"],
                "title": mv.get("title", ""),
                "body": mv.get("body", ""),
            })

    out_mv = DATA / "mindvirus_high_filtered.json"
    with open(out_mv, "w") as f:
        json.dump(mv_compact, f)
    print(f"  \033[1;32m{len(mv_compact)} relevant high-conf MVs → {out_mv.name} "
          f"({out_mv.stat().st_size / 1024:.0f} KB)\033[0m")


if __name__ == "__main__":
    main()
