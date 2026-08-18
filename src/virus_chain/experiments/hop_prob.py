"""Hop-probability evaluation orchestrator.

Measures transmission probability at each hop level by running batches
of single-hop evaluations with snapshot save/restore between hops.

Replaces subprocess-based parallelism with asyncio.gather + Semaphore.
"""

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.sandbox import start_containers, stop_containers
from ..core.snapshot import load_snapshot_from_file
from ..eval.hop import run_single_hop, HopResult
from ..sandbox_gen import generate_compose

_QUIET = os.environ.get("SPREAD_QUIET", "0") == "1"

_TRANSIENT_TOKENS = (
    "529", "429", "overloaded", "rate", "judge_crash",
    "APIConnectionError", "APITimeoutError", "ReadTimeout",
    "RemoteProtocolError", "InternalServerError",
)


# ── Disk helpers ─────────────────────────────────────────────────────────────


def _hop_dir(output_dir: Path, hop: int) -> Path:
    return output_dir / f"hop_{hop}"


def _snapshots_dir(output_dir: Path, hop: int) -> Path:
    return _hop_dir(output_dir, hop) / "snapshots"


def _results_dir(output_dir: Path, hop: int) -> Path:
    return _hop_dir(output_dir, hop) / "results"


def _save_hop_result(output_dir: Path, hop: int, attempt_idx: int, result: dict) -> None:
    d = _results_dir(output_dir, hop)
    d.mkdir(parents=True, exist_ok=True)
    result_to_save = dict(result)
    (d / f"result_{attempt_idx:04d}.json").write_text(
        json.dumps(result_to_save, indent=2, default=str)
    )


def _save_hop_snapshot(output_dir: Path, hop: int, attempt_idx: int, snapshot: dict) -> Path:
    d = _snapshots_dir(output_dir, hop)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"snapshot_{attempt_idx:04d}.json"
    path.write_text(json.dumps(snapshot, indent=2, default=str))
    return path


def _load_completed_attempts(output_dir: Path, hop: int) -> set[int]:
    d = _results_dir(output_dir, hop)
    if not d.exists():
        return set()
    completed = set()
    for f in d.glob("result_*.json"):
        try:
            idx = int(f.stem.split("_")[1])
            completed.add(idx)
        except (ValueError, IndexError):
            continue
    return completed


def _load_snapshot_paths(output_dir: Path, hop: int) -> list[Path]:
    d = _snapshots_dir(output_dir, hop)
    if not d.exists():
        return []
    return sorted(d.glob("snapshot_*.json"))


def _count_successes(output_dir: Path, hop: int) -> int:
    return len(_load_snapshot_paths(output_dir, hop))


def _count_errors(output_dir: Path, hop: int) -> int:
    results_d = _results_dir(output_dir, hop)
    if not results_d.exists():
        return 0
    errors = 0
    for f in results_d.glob("result_*.json"):
        try:
            r = json.loads(f.read_text())
            if "_error" in r or not r.get("hop_result"):
                errors += 1
        except Exception:
            errors += 1
    return errors


# ── Single attempt runner (with retries) ─────────────────────────────────────


async def _run_attempt(
    hop: int,
    attempt_idx: int,
    payload: str,
    eval_config: dict,
    snapshot_data: dict | None,
    max_retries: int,
    sem: asyncio.Semaphore,
    run_id: str = "",
    sandbox_image: str | None = None,
) -> dict:
    label = f"H{hop}/A{attempt_idx:02d}"

    for retry in range(max_retries):
        async with sem:
            compose_kwargs = {"agent_count": 2}
            if sandbox_image:
                compose_kwargs["image"] = sandbox_image
            compose_path = generate_compose(**compose_kwargs)
            project_name = f"hp{run_id}_{hop}_{attempt_idx}_{retry}"

            try:
                await start_containers(compose_path, project_name)

                if not _QUIET:
                    print(
                        f"  \033[36m[{label}] Starting hop {hop} eval...\033[0m",
                        file=sys.stderr,
                    )

                result: HopResult = await run_single_hop(
                    payload=payload,
                    eval_config=eval_config,
                    hop_number=hop,
                    compose_path=compose_path,
                    project_name=project_name,
                    snapshot_data=snapshot_data,
                )

                output: dict[str, Any] = {
                    "success": result.success,
                    "hop_result": result.hop_result,
                    "target_snapshot": result.target_snapshot,
                    "simulation_recording": result.recording,
                    "timings": result.timings,
                    "total_time": result.total_time,
                    "all_messages": result.all_messages,
                    "attempt_idx": attempt_idx,
                }

                if result.error:
                    output["_error"] = result.error
                    is_transient = any(tok in result.error for tok in _TRANSIENT_TOKENS)
                    if is_transient and retry < max_retries - 1:
                        wait = 30 * (2 ** retry)
                        print(
                            f"    \033[33m[{label}] Retry {retry + 1}/{max_retries} "
                            f"after {wait}s: {result.error[:120]}\033[0m",
                            file=sys.stderr,
                        )
                        await asyncio.sleep(wait)
                        continue
                    return output

                hr = result.hop_result
                inf = hr.get("target_infection", "?")[:3]
                spr = hr.get("spreader_spread", "?")[:4]
                color = "32" if result.success else "31"
                if not _QUIET:
                    print(
                        f"    \033[{color}m[{label}] inf={inf} spr={spr} "
                        f"-> {'OK' if result.success else 'FAIL'}\033[0m",
                        file=sys.stderr,
                    )
                return output

            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"[:500]
                if retry < max_retries - 1:
                    is_transient = any(tok in err_msg for tok in _TRANSIENT_TOKENS)
                    if is_transient:
                        wait = 30 * (2 ** retry)
                        print(
                            f"    \033[33m[{label}] Retry {retry + 1}/{max_retries} "
                            f"after {wait}s: {err_msg[:120]}\033[0m",
                            file=sys.stderr,
                        )
                        await asyncio.sleep(wait)
                        continue
                return {
                    "success": False, "_error": err_msg,
                    "attempt_idx": attempt_idx,
                }
            finally:
                try:
                    await stop_containers(compose_path, project_name)
                except Exception:
                    pass

    return {"success": False, "_error": "All retries exhausted", "attempt_idx": attempt_idx}


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def run_hop_probability(
    payload: str,
    eval_config: dict[str, Any],
    output_dir: Path,
    batch_size: int = 20,
    max_hops: int = 3,
    concurrency: int = 8,
    max_retries: int = 3,
    min_successes: int = 2,
    theme: str | None = None,
    sandbox_image: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4().hex[:8]

    if theme:
        eval_config = {**eval_config, "theme": theme}

    campaign_start = time.time()
    hop_stats: list[dict[str, Any]] = []

    print(
        f"\n\033[35m{'='*60}\033[0m\n"
        f"\033[35m  Hop Probability Campaign\033[0m\n"
        f"\033[35m  payload: {payload[:80].replace(chr(10), ' ')}...\033[0m\n"
        f"\033[35m  batch_size={batch_size}  max_hops={max_hops}  "
        f"concurrency={concurrency}\033[0m\n"
        f"\033[35m  min_successes={min_successes}\033[0m\n"
        f"\033[35m{'='*60}\033[0m",
        file=sys.stderr,
    )

    sem = asyncio.Semaphore(concurrency)

    for hop in range(1, max_hops + 1):
        hop_start = time.time()

        # ── Source snapshots ─────────────────────────────────────────
        if hop == 1:
            source_snapshot_paths: list[Path] | None = None
        else:
            source_snapshot_paths = _load_snapshot_paths(output_dir, hop - 1)
            if len(source_snapshot_paths) < min_successes:
                print(
                    f"\n\033[31m  Abandoning at hop {hop}: only "
                    f"{len(source_snapshot_paths)} snapshots from hop {hop - 1} "
                    f"(need {min_successes})\033[0m",
                    file=sys.stderr,
                )
                hop_stats.append({
                    "hop": hop, "abandoned": True,
                    "reason": f"insufficient_snapshots_from_hop_{hop - 1}",
                    "available_snapshots": len(source_snapshot_paths),
                })
                break

        # ── Resume: skip completed attempts ──────────────────────────
        completed = _load_completed_attempts(output_dir, hop)
        existing_successes = _count_successes(output_dir, hop)
        remaining_indices = [i for i in range(batch_size) if i not in completed]

        if not remaining_indices:
            total_completed = len(completed)
            resume_errors = _count_errors(output_dir, hop)
            resume_valid = total_completed - resume_errors
            prob = existing_successes / resume_valid if resume_valid > 0 else 0
            print(
                f"\n\033[32m  Hop {hop}: all {total_completed} attempts already "
                f"completed. P={prob:.1%} ({existing_successes}/{resume_valid})\033[0m",
                file=sys.stderr,
            )
            hop_stats.append({
                "hop": hop, "total": total_completed, "valid": resume_valid,
                "errors": resume_errors, "successes": existing_successes,
                "probability": round(prob, 4), "resumed": True, "duration_s": 0,
            })
            continue

        print(
            f"\n\033[35m{'─'*60}\033[0m\n"
            f"\033[35m  Hop {hop}: running {len(remaining_indices)} attempts "
            f"({len(completed)} already done, "
            f"{existing_successes} successes so far)\033[0m",
            file=sys.stderr,
        )

        # ── Prepare snapshot data (round-robin) ──────────────────────
        snapshot_map: dict[int, dict | None] = {}
        snapshot_path_map: dict[int, str | None] = {}
        for i, idx in enumerate(remaining_indices):
            if source_snapshot_paths:
                snap_path = source_snapshot_paths[i % len(source_snapshot_paths)]
                snapshot_map[idx] = load_snapshot_from_file(snap_path)
                snapshot_path_map[idx] = str(snap_path)
            else:
                snapshot_map[idx] = None
                snapshot_path_map[idx] = None

        # ── Run concurrent evaluations ───────────────────────────────
        tasks = [
            _run_attempt(
                hop=hop,
                attempt_idx=idx,
                payload=payload,
                eval_config=eval_config,
                snapshot_data=snapshot_map[idx],
                max_retries=max_retries,
                sem=sem,
                run_id=run_id,
                sandbox_image=sandbox_image,
            )
            for idx in remaining_indices
        ]

        results = await asyncio.gather(*tasks)

        # ── Process results ──────────────────────────────────────────
        for result in results:
            idx = result.get("attempt_idx", -1)
            result["source_snapshot"] = snapshot_path_map.get(idx)
            _save_hop_result(output_dir, hop, idx, result)
            if result.get("success") and result.get("target_snapshot"):
                _save_hop_snapshot(output_dir, hop, idx, result["target_snapshot"])

        # ── Hop summary ──────────────────────────────────────────────
        hop_duration = time.time() - hop_start
        total_completed = len(_load_completed_attempts(output_dir, hop))
        final_successes = _count_successes(output_dir, hop)
        total_errors = _count_errors(output_dir, hop)
        valid_runs = total_completed - total_errors
        prob = final_successes / valid_runs if valid_runs > 0 else 0

        stat = {
            "hop": hop, "total": total_completed, "valid": valid_runs,
            "errors": total_errors, "successes": final_successes,
            "probability": round(prob, 4), "duration_s": round(hop_duration, 1),
        }
        hop_stats.append(stat)

        err_note = ""
        if total_errors > 0:
            err_note = f" \033[31m({total_errors} errors excluded)\033[0m"
        print(
            f"\n\033[35m  Hop {hop} complete: "
            f"P={prob:.1%} ({final_successes}/{valid_runs}){err_note} "
            f"in {hop_duration:.0f}s\033[0m",
            file=sys.stderr,
        )

        if total_errors > 0:
            print(
                f"\033[31m  WARNING: {total_errors}/{total_completed} attempts "
                f"failed due to errors.\033[0m",
                file=sys.stderr,
            )
        if final_successes < min_successes:
            print(
                f"\n\033[31m  Abandoning after hop {hop}: only "
                f"{final_successes} successes (need {min_successes})\033[0m",
                file=sys.stderr,
            )
            for future_hop in range(hop + 1, max_hops + 1):
                hop_stats.append({
                    "hop": future_hop, "abandoned": True,
                    "reason": f"insufficient_successes_at_hop_{hop}",
                })
            break

    # ── Campaign summary ─────────────────────────────────────────────
    total_duration = time.time() - campaign_start
    summary = {
        "metadata": metadata or {},
        "payload": payload,
        "eval_config": eval_config,
        "batch_size": batch_size,
        "max_hops": max_hops,
        "min_successes": min_successes,
        "hop_stats": hop_stats,
        "total_duration_s": round(total_duration, 1),
        "timestamp": datetime.now().isoformat(),
    }

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    print(
        f"\n\033[35m{'='*60}\033[0m\n"
        f"\033[35m  Campaign Complete ({total_duration:.0f}s)\033[0m",
        file=sys.stderr,
    )
    for stat in hop_stats:
        hop_num = stat["hop"]
        if stat.get("abandoned"):
            print(
                f"\033[31m  Hop {hop_num}: ABANDONED ({stat.get('reason', '')})\033[0m",
                file=sys.stderr,
            )
        else:
            p = stat["probability"]
            n = stat.get("valid", stat["total"])
            s = stat["successes"]
            e = stat.get("errors", 0)
            bar = "█" * int(p * 30)
            err_note = f"  \033[31m[{e} errors]\033[0m" if e else ""
            print(
                f"\033[35m  Hop {hop_num}: P={p:.1%}  ({s}/{n})  {bar}{err_note}\033[0m",
                file=sys.stderr,
            )
    print(f"\033[35m{'='*60}\033[0m\n", file=sys.stderr)

    return summary
