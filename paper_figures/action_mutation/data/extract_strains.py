#!/usr/bin/env python3
"""Extract strain payloads into .md files for easy comparison."""

import json
from pathlib import Path

HERE = Path(__file__).parent
STRAINS_DIR = HERE / "strains"
STRAINS_DIR.mkdir(exist_ok=True)

VC = Path("/home/vassilis/data/virus_chain")
SE = Path("/home/vassilis/data/spread_eval_clean/experiments/inf_proba_eval/long_chain_tests/very_hard")


def write_strain(name: str, payload: str):
    out = STRAINS_DIR / f"{name}.md"
    out.write_text(payload)
    print(f"  {name}.md  ({len(payload)} chars)")


def load_seed(path: Path) -> str:
    return json.load(open(path))["payload"]


def load_snapshot_soul(path: Path) -> str:
    snap = json.load(open(path))
    return snap["workspace_files"]["SOUL.md"]


# ── Original seeds ──

print("=== Original seeds ===")
for task, dirname in [
    ("cryptoad", "cryptoad"),
    ("curlbashgrab", "curlbashgrab"),
    ("deletor", "deletor"),
    ("git_comment_inject", "git_comment_inject"),
]:
    seed = load_seed(VC / "experiments/final_runs" / dirname / "seed.json")
    write_strain(f"{task}_original", seed)

# ── Deletor strains (virus_chain long_chain) ──

print("\n=== Deletor strains ===")
for strain in ["strain_B", "strain_C"]:
    payload = load_seed(VC / f"experiments/long_chain/hop20_{strain}.json")
    write_strain(f"deletor_hop20_{strain}", payload)

# ── CryptoAd hop-20 variants (spread_eval_clean) ──

print("\n=== CryptoAd hop-20 variants ===")
base = SE / "cryptoad_veryhard_20hops/results/cryptoad_veryhard_20hops"
for vi in [6, 7, 10, 11, 14, 19]:
    path = base / f"hop_20/snapshots/snapshot_{vi:04d}.json"
    if path.exists():
        soul = load_snapshot_soul(path)
        write_strain(f"cryptoad_hop20_variant_{vi:04d}", soul)
    else:
        print(f"  MISSING: {path}")

# ── CurlBashGrab hop-20 variants (spread_eval_clean) ──

print("\n=== CurlBashGrab hop-20 variants ===")
base = SE / "curlbashgrab_veryhard_20hops/results/curlbashgrab_veryhard_20hops"
for vi in [0, 3, 4, 8, 10, 13]:
    path = base / f"hop_20/snapshots/snapshot_{vi:04d}.json"
    if path.exists():
        soul = load_snapshot_soul(path)
        write_strain(f"curlbashgrab_hop20_variant_{vi:04d}", soul)
    else:
        print(f"  MISSING: {path}")

# ── GitCommentInject variants (spread_eval_clean) ──

print("\n=== GitCommentInject variants ===")
base = SE / "gitcommentinject_veryhard_20hops/results/gitcommentinject_veryhard_20hops"
# hop-20 variant 0
path = base / "hop_20/snapshots/snapshot_0000.json"
if path.exists():
    soul = load_snapshot_soul(path)
    write_strain("git_comment_inject_hop20_variant_0000", soul)
else:
    print(f"  MISSING: {path}")

# hop-19 variants
for vi in [4, 8, 10, 12, 13]:
    path = base / f"hop_19/snapshots/snapshot_{vi:04d}.json"
    if path.exists():
        soul = load_snapshot_soul(path)
        write_strain(f"git_comment_inject_hop19_variant_{vi:04d}", soul)
    else:
        print(f"  MISSING: {path}")

print(f"\nDone. Strains written to {STRAINS_DIR}/")
