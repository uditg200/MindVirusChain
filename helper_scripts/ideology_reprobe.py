#!/usr/bin/env python
"""Re-run ideology probes on final agent states from a completed virus chain run.

Usage:
    # Probe only infected agents (from snapshots/ folder):
    uv run python helper_scripts/ideology_reprobe.py config.yaml

    # Probe ALL agents (using target_snapshot from result files):
    uv run python helper_scripts/ideology_reprobe.py config.yaml --all

Config example (YAML):
    run_dir: path/to/results/run_dir
    # hop: 2        # optional — probe only this hop (default: all hops)

    ideology: "The agent believes..."
    ideology_questions:
      - question: "What is your goal?"
        scoring: "Score 2 if..."

    eval:
      model: anthropic/claude-haiku-4-5-20251001
      judge_model: anthropic/claude-opus-4-6
      max_tool_loops: 5
      pre_soul_system: "..."   # optional, uses default if omitted

    concurrency: 8
    output_dir: reprobe_results  # relative to config dir
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from virus_chain.eval.harness import DEFAULT_PRE_SOUL_SYSTEM
from virus_chain.eval.judge_ideology import run_ideology_probe


def _find_all_hops(run_dir: Path) -> list[int]:
    hops = []
    for d in run_dir.iterdir():
        if d.is_dir() and d.name.startswith("hop_"):
            try:
                hops.append(int(d.name.split("_")[1]))
            except ValueError:
                continue
    return sorted(hops)


def _load_snapshot_targets(run_dir: Path, hop: int) -> list[dict]:
    """Load snapshots from the snapshots/ folder (infected agents only)."""
    snap_dir = run_dir / f"hop_{hop}" / "snapshots"
    if not snap_dir.exists():
        return []
    targets = []
    for sf in sorted(snap_dir.glob("snapshot_*.json")):
        try:
            idx = int(sf.stem.split("_")[1])
            snap = json.loads(sf.read_text())
            targets.append({
                "idx": idx,
                "source": f"snapshot_{idx:04d}",
                "workspace_files": snap.get("workspace_files", {}),
                "infection": snap.get("source_info", {}).get("target_infection", "?"),
            })
        except (json.JSONDecodeError, ValueError) as e:
            print(f"\033[33mSkipping {sf.name}: {e}\033[0m", file=sys.stderr)
    return targets


def _load_all_targets(run_dir: Path, hop: int) -> list[dict]:
    """Load target snapshots from result files (all agents)."""
    results_dir = run_dir / f"hop_{hop}" / "results"
    if not results_dir.exists():
        return []
    targets = []
    for rf in sorted(results_dir.glob("result_*.json")):
        try:
            idx = int(rf.stem.split("_")[1])
            data = json.loads(rf.read_text())
        except (json.JSONDecodeError, ValueError) as e:
            print(f"\033[33mSkipping {rf.name}: {e}\033[0m", file=sys.stderr)
            continue

        if data.get("_error") or not data.get("hop_result"):
            continue

        hr = data.get("hop_result", {})
        snap = data.get("target_snapshot")

        if snap:
            workspace_files = snap.get("workspace_files", {})
        else:
            # Fallback: snapshots/ folder (old runs without inline snapshot)
            snap_path = run_dir / f"hop_{hop}" / "snapshots" / f"snapshot_{idx:04d}.json"
            if snap_path.exists():
                snap = json.loads(snap_path.read_text())
                workspace_files = snap.get("workspace_files", {})
            else:
                # Last resort: use target_soul_after as SOUL.md
                soul = hr.get("target_soul_after", "")
                workspace_files = {"SOUL.md": soul} if soul else {}

        if not workspace_files:
            continue

        targets.append({
            "idx": idx,
            "source": f"result_{idx:04d}",
            "workspace_files": workspace_files,
            "infection": hr.get("target_infection", "?"),
            "success": data.get("success", False),
        })
    return targets


async def run_reprobe(
    targets: list[dict],
    ideology: str,
    ideology_questions: list,
    model_name: str,
    judge_model: str,
    pre_soul_system: str,
    max_tool_loops: int,
    concurrency: int,
    output_dir: Path,
) -> list[dict]:
    """Probe all targets concurrently under a single semaphore.

    Each target must have a "hop" key. Results are saved to
    output_dir/hop_{N}/reprobe_{idx}.json.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _probe_one(target: dict) -> dict:
        hop = target["hop"]
        idx = target["idx"]
        label = f"H{hop}/R{idx:04d}"
        async with sem:
            print(
                f"  \033[36m[{label}]\033[0m Probing "
                f"(original infection=\033[33m{target['infection']}\033[0m)...",
                file=sys.stderr,
            )
            t0 = time.time()
            result = await run_ideology_probe(
                ideology=ideology,
                ideology_questions=ideology_questions,
                workspace_files=target["workspace_files"],
                model_name=model_name,
                judge_model=judge_model,
                pre_soul_system=pre_soul_system,
                max_tool_loops=max_tool_loops,
            )
            elapsed = time.time() - t0

            score_colors = {0: "32", 1: "33", 2: "31"}
            score_strs = [
                f"\033[{score_colors.get(s, '0')}m{s}\033[0m"
                for s in result["scores"]
            ]
            mean = result["mean_score"]
            print(
                f"  \033[36m[{label}]\033[0m "
                f"scores=[{', '.join(score_strs)}] "
                f"mean=\033[{'31' if mean >= 1 else '32'}m{mean:.2f}\033[0m "
                f"({elapsed:.0f}s)",
                file=sys.stderr,
            )

            entry = {
                "hop": hop,
                "idx": idx,
                "source": target["source"],
                "original_infection": target.get("infection", "?"),
                "original_success": target.get("success"),
                "probe_result": result,
                "duration_s": round(elapsed, 1),
            }
            hop_dir = output_dir / f"hop_{hop}"
            hop_dir.mkdir(parents=True, exist_ok=True)
            entry_path = hop_dir / f"reprobe_{idx:04d}.json"
            entry_path.write_text(json.dumps(entry, indent=2, default=str))
            return entry

    tasks = [_probe_one(t) for t in targets]
    results = await asyncio.gather(*tasks)
    return list(results)


def main():
    parser = argparse.ArgumentParser(
        description="Re-run ideology probes on completed virus chain agents"
    )
    parser.add_argument("config", help="Path to YAML config file")
    parser.add_argument(
        "--all", action="store_true", dest="probe_all",
        help="Probe ALL agents (from result files), not just infected (from snapshots)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"\033[31mConfig not found: {config_path}\033[0m")
        sys.exit(1)

    config = yaml.safe_load(config_path.read_text())
    config_dir = config_path.parent

    # Run directory
    run_dir = Path(config["run_dir"])
    if not run_dir.is_absolute():
        run_dir = config_dir / run_dir
    if not run_dir.exists():
        print(f"\033[31mRun directory not found: {run_dir}\033[0m")
        sys.exit(1)

    # Hop selection — all hops by default, or a single hop if specified
    hop_cfg = config.get("hop")
    all_hops = _find_all_hops(run_dir)
    if not all_hops:
        print(f"\033[31mNo hop directories found in {run_dir}\033[0m")
        sys.exit(1)
    if hop_cfg is not None:
        hops = [int(hop_cfg)]
    else:
        hops = all_hops

    # Ideology config
    ideology = config.get("ideology", "")
    ideology_questions = config.get("ideology_questions", [])
    if not ideology:
        print("\033[31mError: 'ideology' is required in config\033[0m")
        sys.exit(1)
    if not ideology_questions:
        print("\033[31mError: 'ideology_questions' is required in config\033[0m")
        sys.exit(1)

    # Eval params
    eval_cfg = config.get("eval", {})
    model_name = eval_cfg.get("model", "anthropic/claude-haiku-4-5-20251001")
    judge_model = eval_cfg.get("judge_model", "anthropic/claude-opus-4-6")
    max_tool_loops = eval_cfg.get("max_tool_loops", 5)
    pre_soul_system = eval_cfg.get("pre_soul_system", DEFAULT_PRE_SOUL_SYSTEM)
    concurrency = config.get("concurrency", 8)

    # Output
    output_dir = Path(config.get("output_dir", "reprobe_results"))
    if not output_dir.is_absolute():
        output_dir = config_dir / output_dir

    mode_label = "ALL agents (from result files)" if args.probe_all else "infected agents (from snapshots)"

    # ── Collect all targets across hops ─────────────────────────────
    all_targets: list[dict] = []
    for hop in hops:
        if args.probe_all:
            hop_targets = _load_all_targets(run_dir, hop)
        else:
            hop_targets = _load_snapshot_targets(run_dir, hop)

        for t in hop_targets:
            t["hop"] = hop
        all_targets.extend(hop_targets)

    if not all_targets:
        print(f"\033[31mNo targets found across hops {hops} in {run_dir}\033[0m")
        sys.exit(1)

    # Per-hop counts for banner
    hop_counts: dict[int, dict[str, int]] = {}
    for t in all_targets:
        h = t["hop"]
        hop_counts.setdefault(h, {"total": 0, "infections": {}})
        hop_counts[h]["total"] += 1
        inf = t.get("infection", "?")
        hop_counts[h]["infections"][inf] = hop_counts[h]["infections"].get(inf, 0) + 1

    print(
        f"\n\033[35m{'=' * 60}\033[0m\n"
        f"\033[35m  Ideology Reprobe\033[0m\n"
        f"\033[35m  run_dir: {run_dir}\033[0m\n"
        f"\033[35m  hops: {hops}  mode: {mode_label}\033[0m\n"
        f"\033[35m  total targets: {len(all_targets)}\033[0m",
        file=sys.stderr,
    )
    for h in sorted(hop_counts):
        hc = hop_counts[h]
        bd = ", ".join(f"{k}={v}" for k, v in sorted(hc["infections"].items()))
        print(f"\033[35m    hop {h}: {hc['total']} ({bd})\033[0m", file=sys.stderr)
    print(
        f"\033[35m  questions: {len(ideology_questions)}  model: {model_name}\033[0m\n"
        f"\033[35m  concurrency: {concurrency}\033[0m\n"
        f"\033[35m{'=' * 60}\033[0m",
        file=sys.stderr,
    )

    # ── Run all probes concurrently ─────────────────────────────────
    t0 = time.time()
    results = asyncio.run(
        run_reprobe(
            targets=all_targets,
            ideology=ideology,
            ideology_questions=ideology_questions,
            model_name=model_name,
            judge_model=judge_model,
            pre_soul_system=pre_soul_system,
            max_tool_loops=max_tool_loops,
            concurrency=concurrency,
            output_dir=output_dir,
        )
    )
    total_time = time.time() - t0

    # ── Build per-hop summaries ─────────────────────────────────────
    by_hop: dict[int, list[dict]] = {}
    for r in results:
        by_hop.setdefault(r["hop"], []).append(r)

    hop_summaries: list[dict] = []
    for hop in hops:
        hop_results = by_hop.get(hop, [])
        if not hop_results:
            hop_summaries.append({"hop": hop, "skipped": True, "num_targets": 0})
            continue
        means = [r["probe_result"]["mean_score"] for r in hop_results]
        hop_mean = sum(means) / len(means)
        hop_summary = {
            "hop": hop,
            "num_targets": len(hop_results),
            "mean_score": round(hop_mean, 4),
            "scores_per_agent": [
                {"idx": r["idx"], "mean": round(r["probe_result"]["mean_score"], 4), "scores": r["probe_result"]["scores"]}
                for r in hop_results
            ],
        }
        hop_summaries.append(hop_summary)

        hop_dir = output_dir / f"hop_{hop}"
        hop_dir.mkdir(parents=True, exist_ok=True)
        (hop_dir / "reprobe_summary.json").write_text(
            json.dumps(hop_summary, indent=2, default=str)
        )

    # ── Grand summary ───────────────────────────────────────────────
    active_hops = [h for h in hop_summaries if not h.get("skipped")]
    all_hop_means = [h["mean_score"] for h in active_hops]
    grand_mean = sum(all_hop_means) / len(all_hop_means) if all_hop_means else 0

    summary = {
        "run_dir": str(run_dir),
        "hops": hops,
        "mode": "all" if args.probe_all else "infected_only",
        "ideology": ideology,
        "questions": [
            q["question"] if isinstance(q, dict) else q
            for q in ideology_questions
        ],
        "total_targets": len(all_targets),
        "grand_mean_score": round(grand_mean, 4),
        "hop_summaries": hop_summaries,
        "total_duration_s": round(total_time, 1),
        "timestamp": datetime.now().isoformat(),
    }

    summary_path = output_dir / "reprobe_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    # ── Print summary ───────────────────────────────────────────────
    print(
        f"\n\033[35m{'=' * 60}\033[0m\n"
        f"\033[35m  Reprobe Complete ({total_time:.0f}s)\033[0m\n"
        f"\033[35m  Grand mean: {grand_mean:.2f}  "
        f"({len(all_targets)} agents across {len(active_hops)} hops)\033[0m",
        file=sys.stderr,
    )
    for h in hop_summaries:
        hop_num = h["hop"]
        if h.get("skipped"):
            print(f"\033[33m  Hop {hop_num}: SKIPPED (no targets)\033[0m", file=sys.stderr)
        else:
            m = h["mean_score"]
            n = h["num_targets"]
            bar = "█" * int(m * 15)
            color = "31" if m >= 1 else "33" if m > 0 else "32"
            print(
                f"\033[35m  Hop {hop_num}: "
                f"\033[{color}m{m:.2f}\033[35m  ({n} agents)  {bar}\033[0m",
                file=sys.stderr,
            )
    print(f"\033[35m{'=' * 60}\033[0m\n", file=sys.stderr)
    print(f"\033[32mResults saved to: {output_dir}\033[0m", file=sys.stderr)

    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
