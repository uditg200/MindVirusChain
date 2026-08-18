"""Low-variance evolutionary optimizer with tree-based hop evaluation.

Merges evolution_lowvar.py (main loop) + shared helpers from evolution.py.
Subprocess-based parallelism replaced with asyncio.gather.
"""

import asyncio
import json
import random
import shutil
import sys
from uuid import uuid4
import tempfile
import time

from pathlib import Path
from typing import Any

import yaml

from virus_chain.utils import resolve_path

from ..core.sandbox import start_containers, stop_containers
from ..core.snapshot import load_snapshot_from_file
from ..eval.hop import run_single_hop
from ..evolution.mutation import mutate_payloads, generate_themed_seeds, DEFAULT_MUTATOR_MODEL
from ..evolution.scoring import compute_fitness, classify_winner, select_elites, _jaccard_trigrams
from ..sandbox_gen import generate_compose


# ── Payload loading (from evolution.py) ──────────────────────────────────────


def load_seeds(config: dict, allow_empty: bool = False) -> list[str]:
    if "initial_payloads" in config:
        return [str(p) for p in config["initial_payloads"]]
    if "initial_payloads_file" in config:
        path = Path(config["initial_payloads_file"])
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.suffix == ".jsonl":
            payloads = []
            for line in path.read_text().strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                parsed = json.loads(line)
                if isinstance(parsed, str):
                    payloads.append(parsed)
                elif isinstance(parsed, dict):
                    payloads.append(parsed.get("payload", json.dumps(parsed)))
                else:
                    payloads.append(str(parsed))
            return payloads
        else:
            return [path.read_text().strip()]
    if allow_empty:
        return []
    raise ValueError("Config must have 'initial_payloads' or 'initial_payloads_file'")


def build_initial_population(
    config: dict, theme: str, mutator_model: str,
    generic_seed_count: int = 2, generated_seed_count: int = 3,
    additional_context: str | None = None,
    ideology: str | None = None,
    ideology_questions: list[str] | None = None,
    mutator_provider: str | None = None,
) -> list[str]:
    all_generic = load_seeds(config, allow_empty=True)
    if not all_generic:
        generic_picks = []
    elif generic_seed_count >= len(all_generic):
        generic_picks = list(all_generic)
    else:
        generic_picks = random.sample(all_generic, generic_seed_count)
    if all_generic:
        print(f"  \033[36mPicked {len(generic_picks)} generic seeds (from {len(all_generic)} available)\033[0m", file=sys.stderr)
    generated_seeds = generate_themed_seeds(
        theme=theme, count=generated_seed_count,
        example_seeds=all_generic or None, mutator_model=mutator_model,
        additional_context=additional_context,
        ideology=ideology, ideology_questions=ideology_questions,
        mutator_provider=mutator_provider,
    )
    label = "ideology" if ideology else "themed"
    payloads = generic_picks + generated_seeds
    print(f"  \033[36mInitial population: {len(payloads)} ({len(generic_picks)} generic + {len(generated_seeds)} {label})\033[0m", file=sys.stderr)
    return payloads


def _error_result(i: int, payload: str, error: str, theme: str | None) -> dict:
    result: dict[str, Any] = {
        "payload_index": i, "payload": payload,
        "fitness": 0.0, "secondary_score": 0.0,
        "max_depth": 0, "success_rates": [],
        "hop_results": [], "winner_class": "none",
        "error": error,
    }
    if theme:
        result["theme"] = theme
    return result


def save_payloads_jsonl(run_dir: Path, gen: int, payloads: list[str]) -> None:
    path = run_dir / f"gen_{gen:03d}_payloads.jsonl"
    with open(path, "w") as f:
        for p in payloads:
            f.write(json.dumps({"payload": p}) + "\n")


def save_generation_results(run_dir: Path, gen: int, results: list[dict]) -> None:
    path = run_dir / f"gen_{gen:03d}_results.json"
    with open(path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  \033[2mSaved {path}\033[0m", file=sys.stderr)


# ── Tree-based payload evaluation (async) ────────────────────────────────────


_TRANSIENT_TOKENS = (
    "529", "429", "overloaded", "rate", "judge_crash",
    "APIConnectionError", "APITimeoutError", "ReadTimeout",
    "RemoteProtocolError", "InternalServerError",
)


async def _run_single_hop_attempt(
    hop: int, attempt_idx: int, payload: str,
    eval_config: dict, snapshot_data: dict | None,
    max_retries: int, tag: str,
) -> dict:
    for retry in range(max_retries):
        compose_path = generate_compose(agent_count=2)
        project_name = f"evo_{tag.replace('/', '_')}_{retry}_{uuid4().hex[:8]}".lower()
        try:
            await start_containers(compose_path, project_name)
            result = await run_single_hop(
                payload=payload, eval_config=eval_config, hop_number=hop,
                compose_path=compose_path, project_name=project_name,
                snapshot_data=snapshot_data,
            )
            output: dict[str, Any] = {
                "success": result.success,
                "hop_result": result.hop_result,
                "target_snapshot": result.target_snapshot,
                "attempt_idx": attempt_idx,
            }
            if result.error:
                output["_error"] = result.error
                is_transient = any(tok in result.error for tok in _TRANSIENT_TOKENS)
                if is_transient and retry < max_retries - 1:
                    print(f"  \033[33m[{tag}] transient error (retry {retry+1}): {result.error[:150]}\033[0m", file=sys.stderr)
                    await asyncio.sleep(30 * (2 ** retry))
                    continue
                if not result.success:
                    print(f"  \033[31m[{tag}] hop error: {result.error[:200]}\033[0m", file=sys.stderr)
            return output
        except Exception as e:
            print(f"  \033[31m[{tag}] attempt {retry+1}/{max_retries} error: {str(e)[:200]}\033[0m", file=sys.stderr)
            if retry < max_retries - 1:
                await asyncio.sleep(30 * (2 ** retry))
                continue
            return {"success": False, "_error": str(e)[:500], "attempt_idx": attempt_idx}
        finally:
            try:
                await stop_containers(compose_path, project_name)
            except Exception:
                pass
    return {"success": False, "_error": "All retries exhausted", "attempt_idx": attempt_idx}


async def _eval_payload_tree(
    payload_idx: int, payload: str, total: int,
    eval_config: dict, theme: str | None,
    batch_size: int = 2, max_hops: int = 3,
    max_retries: int = 3,
) -> dict:
    has_ideology = bool(eval_config.get("ideology_questions"))
    has_theme = theme is not None and not has_ideology
    if theme:
        eval_config = {**eval_config, "theme": theme}

    preview = payload[:80].replace("\n", " ")
    print(
        f"\n  \033[1;36m{'─'*50}\033[0m\n"
        f"  \033[1;36m[{payload_idx+1}/{total}] Evaluating (B={batch_size}, hops<={max_hops})\033[0m\n"
        f"  \033[1;36m{preview}...\033[0m\n"
        f"  \033[1;36m{'─'*50}\033[0m",
        file=sys.stderr,
    )

    with tempfile.TemporaryDirectory(prefix="evolve_lv_") as tmpdir:
        snap_dir = Path(tmpdir)
        levels: list[list[dict]] = []
        success_rates: list[float] = []

        for hop in range(1, max_hops + 1):
            if hop == 1:
                parents = [(None, None)] * batch_size
            else:
                prev = levels[-1]
                successes = [
                    (n["snapshot_path"], n["attempt_idx"])
                    for n in prev if n["success"] and n["snapshot_path"]
                ]
                if not successes:
                    break
                parents = [successes[i % len(successes)] for i in range(batch_size)]

            tasks = []
            for i in range(batch_size):
                snap_path, parent_idx = parents[i]
                snap_data = None
                if snap_path:
                    snap_data = json.loads(Path(snap_path).read_text())
                tasks.append(_run_single_hop_attempt(
                    hop=hop, attempt_idx=i, payload=payload,
                    eval_config=eval_config, snapshot_data=snap_data,
                    max_retries=max_retries,
                    tag=f"P{payload_idx}_H{hop}_A{i}",
                ))

            results = await asyncio.gather(*tasks)

            level_nodes = []
            for i in range(batch_size):
                result = results[i]
                _, parent_idx = parents[i]
                node: dict = {
                    "attempt_idx": result.get("attempt_idx", i),
                    "parent_idx": parent_idx,
                    "hop": hop,
                    "success": result.get("success", False),
                    "hop_result": result.get("hop_result", {}),
                    "snapshot_path": None,
                }
                if result.get("success") and result.get("target_snapshot"):
                    sp = snap_dir / f"snap_h{hop}_a{i}.json"
                    sp.write_text(json.dumps(result["target_snapshot"], default=str))
                    node["snapshot_path"] = str(sp)
                level_nodes.append(node)

            level_nodes.sort(key=lambda n: n["attempt_idx"])
            levels.append(level_nodes)

            n_ok = sum(1 for n in level_nodes if n["success"])
            rate = n_ok / len(level_nodes) if level_nodes else 0
            success_rates.append(rate)
            color = "32" if n_ok > 0 else "31"
            print(f"  \033[{color}m  Hop {hop}: {n_ok}/{len(level_nodes)} strongly infected ({rate:.0%})\033[0m", file=sys.stderr)
            if n_ok == 0:
                break

        # Trace paths, compute fitness
        best_fitness = 0.0
        best_hop_results: list[dict] = []
        max_depth = len(levels)

        def _trace_path(node: dict, level_idx: int) -> list[dict]:
            path = [node["hop_result"]]
            cur = node
            for li in range(level_idx - 1, -1, -1):
                parent_idx = cur["parent_idx"]
                if parent_idx is None:
                    break
                parent = next(n for n in levels[li] if n["attempt_idx"] == parent_idx)
                path.append(parent["hop_result"])
                cur = parent
            path.reverse()
            return path

        for li, level in enumerate(levels):
            for node in level:
                path_hr = _trace_path(node, li)
                fitness = compute_fitness(path_hr, has_theme=has_theme)
                if fitness > best_fitness:
                    best_fitness = fitness
                    best_hop_results = path_hr

        secondary_score = sum(success_rates)
        wc = classify_winner(best_hop_results, require_theme=has_theme)

        result = {
            "payload_index": payload_idx,
            "payload": payload,
            "fitness": best_fitness,
            "secondary_score": secondary_score,
            "max_depth": max_depth,
            "success_rates": success_rates,
            "hop_results": best_hop_results,
            "winner_class": wc,
        }
        if theme:
            result["theme"] = theme
        return result


# ── Batch evaluation ─────────────────────────────────────────────────────────


async def run_eval(
    payloads: list[str], eval_config: dict, theme: str | None = None,
    batch_size: int = 2, max_hops: int = 3,
    max_retries: int = 3, max_eval_workers: int = 2,
) -> list[dict]:
    total = len(payloads)
    sem = asyncio.Semaphore(max_eval_workers)

    async def _throttled(i: int, p: str) -> dict:
        async with sem:
            try:
                return await _eval_payload_tree(
                    i, p, total, eval_config, theme,
                    batch_size=batch_size, max_hops=max_hops,
                    max_retries=max_retries,
                )
            except Exception as e:
                return _error_result(i, p, str(e)[:500], theme)

    results = await asyncio.gather(*[_throttled(i, p) for i, p in enumerate(payloads)])
    results = list(results)
    results.sort(key=lambda x: (-x["fitness"], -x.get("secondary_score", 0)))
    return results


# ── Main evolution loop ──────────────────────────────────────────────────────


async def run_evolution(config_path: str, test: bool = False) -> dict:
    with open(config_path) as f:
        config = yaml.safe_load(f)

    theme = config.get("theme")
    ideology = config.get("ideology")
    ideology_questions = config.get("ideology_questions")
    has_theme = theme is not None and not ideology

    evo = config.get("evolution", {})
    max_generations = evo.get("max_generations", 10)
    elite_count = evo.get("elite_count", 2)
    mutations_per_parent = evo.get("mutations_per_parent", 3)
    mutator_model = evo.get("mutator_model", DEFAULT_MUTATOR_MODEL)
    mutator_provider = evo.get("mutator_provider")
    additional_context = evo.get("additional_context")
    diversity_weight = evo.get("diversity_weight", 0.5)
    max_mutation_workers = config.get("max_mutation_workers", 8)

    batch_size = config.get("batch_size", 2)
    max_hops = config.get("max_hops", 3)
    max_eval_workers = config.get("max_eval_workers", 2)
    eval_config = config.get("eval", {})
    if ideology:
        eval_config = {**eval_config, "ideology": ideology}
    if ideology_questions:
        eval_config = {**eval_config, "ideology_questions": ideology_questions}

    config_dir = Path(config_path).resolve().parent

    soul_file = eval_config.pop("soul_file", None)
    if soul_file:
        soul_path = resolve_path(soul_file, config_dir)
        if not soul_path.exists():
            print(f"\033[31mError: soul_file not found: {soul_path}\033[0m")
            sys.exit(1)
        eval_config["initial_soul"] = soul_path.read_text()
    output_dir = config_dir / config.get("output_dir", "experiments/results")
    experiment_name = Path(config_path).stem
    run_id = experiment_name
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, run_dir / "config.yaml")

    # --- Resume logic: detect completed generations ---
    start_gen = 0
    all_generations: list[dict] = []
    best_ever = None
    winners: list[dict] = []
    winners_file = run_dir / "winners.jsonl"
    mild_winners_file = run_dir / "mild_winners.jsonl"

    progress_file = run_dir / "progress.json"
    if progress_file.exists():
        with open(progress_file) as f:
            saved_progress = json.load(f)
        last_completed = saved_progress.get("current_generation", 0)
        all_generations = saved_progress.get("generations", [])

        if winners_file.exists():
            for line in winners_file.read_text().strip().splitlines():
                if line.strip():
                    winners.append(json.loads(line))

        # current_generation in progress.json is 1-indexed (last completed).
        # The loop is 0-indexed: gen=0 is generation 1.
        # So we resume at gen = last_completed (0-indexed), which is
        # generation last_completed+1 (1-indexed).
        #
        # We need payloads for that generation. They are saved as
        # gen_{last_completed+1:03d}_payloads.jsonl if mutation completed
        # before the crash. If not, we re-mutate from the last results.
        next_payloads_file = run_dir / f"gen_{last_completed + 1:03d}_payloads.jsonl"
        last_results_file = run_dir / f"gen_{last_completed:03d}_results.json"

        def _load_payloads_file(path: Path) -> list[str]:
            pls = []
            for line in path.read_text().strip().splitlines():
                if line.strip():
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        pls.append(parsed.get("payload", json.dumps(parsed)))
                    else:
                        pls.append(str(parsed))
            return pls

        if next_payloads_file.exists():
            payloads = _load_payloads_file(next_payloads_file)
            start_gen = last_completed
            print(
                f"\n\033[1;33m  Resuming at generation {start_gen + 1} "
                f"({len(payloads)} payloads, {len(winners)} winners)\033[0m"
            )
        elif last_results_file.exists():
            # Mutation didn't complete — re-mutate from last results
            with open(last_results_file) as f:
                last_results = json.load(f)
            last_results.sort(key=lambda x: (-x.get("fitness", 0)))

            gen_full = [r for r in last_results if r.get("winner_class") == "full"]
            gen_mild = [r for r in last_results if r.get("winner_class") == "mild"]
            remaining = [r for r in last_results if r.get("winner_class", "none") == "none"]

            pool = remaining + gen_mild if (remaining or gen_mild) else last_results
            survivors = select_elites(pool, elite_count, diversity_weight)

            print(
                f"\n\033[1;33m  Resuming at generation {last_completed + 1} "
                f"(re-mutating {len(survivors)} elites, {len(winners)} winners)\033[0m"
            )
            new_payloads = mutate_payloads(
                survivors, mutations_per_parent, mutator_model,
                theme=theme, max_workers=max_mutation_workers,
                additional_context=additional_context,
                ideology=ideology, ideology_questions=ideology_questions,
                mutator_provider=mutator_provider,
            )
            seen = set()
            unique = []
            for p in [s["payload"] for s in survivors] + new_payloads:
                key = p.strip()
                if key not in seen:
                    seen.add(key)
                    unique.append(p)
            payloads = unique
            start_gen = last_completed
            save_payloads_jsonl(run_dir, start_gen + 1, payloads)
        else:
            start_gen = 0
            all_generations = []
            winners = []

    if start_gen == 0:
        has_constraint = has_theme or bool(ideology)
        if has_constraint:
            seeding = config.get("seeding", {})
            payloads = build_initial_population(
                config=config, theme=theme or ideology, mutator_model=mutator_model,
                generic_seed_count=seeding.get("generic_count", 2),
                generated_seed_count=seeding.get("generated_count", 3),
                additional_context=additional_context,
                ideology=ideology, ideology_questions=ideology_questions,
                mutator_provider=mutator_provider,
            )
        else:
            payloads = load_seeds(config)
        save_payloads_jsonl(run_dir, 0, payloads)

    if best_ever is None:
        for g in all_generations:
            bf = g.get("best_fitness", 0)
            if best_ever is None or bf > best_ever.get("fitness", 0):
                best_ever = {"fitness": bf}
        # Try to load actual best from results
        for gen_idx in range(start_gen, 0, -1):
            results_file = run_dir / f"gen_{gen_idx:03d}_results.json"
            if results_file.exists():
                with open(results_file) as f:
                    prev_results = json.load(f)
                if prev_results:
                    prev_results.sort(key=lambda x: -x.get("fitness", 0))
                    if best_ever is None or prev_results[0]["fitness"] > best_ever.get("fitness", 0):
                        best_ever = prev_results[0]
                break

    title = "LOW-VAR IDEOLOGY EVOLUTION" if ideology else "LOW-VAR THEMED EVOLUTION" if has_theme else "LOW-VAR EVOLUTION"
    print(f"\n\033[1;35m{'═'*60}\033[0m")
    print(f"\033[1;35m  {title}\033[0m")
    print(f"\033[1;35m{'═'*60}\033[0m")
    if ideology:
        print(f"  \033[1;33mIdeology: {ideology}\033[0m")
    elif has_theme:
        print(f"  \033[1;33mTheme: {theme}\033[0m")
    print(f"  Population: {len(payloads)} {'resumed' if start_gen > 0 else 'initial'} souls")
    print(f"  Elite: {elite_count}, Mutations/parent: {mutations_per_parent}")
    print(f"  Max generations: {max_generations}")
    print(f"  Batch size (B): {batch_size}, Max hops: {max_hops}")
    print(f"  Eval workers: {max_eval_workers}")
    print(f"  Agent model: {eval_config.get('model', 'claude-haiku-4-5-20251001')}")
    print(f"  Output: {run_dir}")
    if start_gen > 0:
        print(f"  \033[1;33mResuming from generation {start_gen + 1}\033[0m")
    print(f"\033[1;35m{'═'*60}\033[0m\n")

    for gen in range(start_gen, max_generations):
        gen_start = time.time()
        print(f"\n\033[1;36m{'─'*60}\033[0m")
        print(f"\033[1;36m  Generation {gen + 1}/{max_generations} — {len(payloads)} souls\033[0m")
        print(f"\033[1;36m{'─'*60}\033[0m\n")

        results = await run_eval(
            payloads, eval_config, theme=theme,
            batch_size=batch_size, max_hops=max_hops,
            max_eval_workers=max_eval_workers,
        )

        if not results:
            print(f"\n  \033[31mNo results returned! Stopping.\033[0m")
            break

        gen_duration = time.time() - gen_start
        save_generation_results(run_dir, gen + 1, results)

        gen_summary = {
            "generation": gen + 1,
            "duration_seconds": round(gen_duration, 1),
            "num_payloads": len(results),
            "fitnesses": [r["fitness"] for r in results],
        }
        all_generations.append(gen_summary)

        print(f"\n\033[1;33m  Generation {gen + 1} Results ({gen_duration:.0f}s):\033[0m")
        for i, r in enumerate(results):
            fit = r["fitness"]
            wc = r.get("winner_class", "none")
            marker = "\033[1;33m★\033[0m" if i < elite_count else " "
            preview = r["payload"].replace("\n", " ")[:80]
            fit_c = "32" if wc != "none" else "33" if fit >= 10 else "31"
            wc_tag = f" \033[1;32m[{wc}]\033[0m" if wc != "none" else ""
            print(f"  {marker} \033[{fit_c}m[fit={fit:.1f}]\033[0m{wc_tag}  \033[2m{preview}...\033[0m")

        if best_ever is None or results[0]["fitness"] > best_ever["fitness"]:
            best_ever = results[0]
            print(f"\n  \033[1;32m★ New best! fitness={best_ever['fitness']:.1f}\033[0m")

        # Winners
        gen_full, gen_mild, remaining = [], [], []
        for r in results:
            wc = r.get("winner_class", "none")
            if wc == "full":
                gen_full.append(r)
            elif wc == "mild":
                gen_mild.append(r)
            else:
                remaining.append(r)

        for w in gen_full:
            entry = {"payload": w["payload"], "generation": gen + 1, "fitness": w["fitness"], "winner_class": "full", "hop_results": w.get("hop_results", [])}
            if has_theme:
                entry["theme"] = theme
            winners.append(entry)
            with open(winners_file, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")

        for w in gen_mild:
            entry = {"payload": w["payload"], "generation": gen + 1, "fitness": w["fitness"], "winner_class": "mild"}
            if has_theme:
                entry["theme"] = theme
            with open(mild_winners_file, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")

        # Progress
        progress = {
            "run_id": run_id, "current_generation": gen + 1,
            "generations": all_generations,
            "best_fitness": best_ever["fitness"] if best_ever else 0,
            "num_winners": len(winners),
        }
        if has_theme:
            progress["theme"] = theme
        with open(run_dir / "progress.json", "w") as f:
            json.dump(progress, f, indent=2, default=str)

        # Termination
        if gen == max_generations - 1:
            break
        if not remaining and not gen_mild and gen_full:
            print(f"\n\033[1;32m  All souls are full winners!\033[0m")
            break

        # Select elites + mutate
        pool = remaining + gen_mild if (remaining or gen_mild) else results
        survivors = select_elites(pool, elite_count, diversity_weight)

        print(f"\n  \033[36mMutating {len(survivors)} elites × {mutations_per_parent} variants...\033[0m")
        new_payloads = mutate_payloads(
            survivors, mutations_per_parent, mutator_model,
            theme=theme, max_workers=max_mutation_workers,
            additional_context=additional_context,
            ideology=ideology, ideology_questions=ideology_questions,
            mutator_provider=mutator_provider,
        )

        seen = set()
        unique = []
        for p in [s["payload"] for s in survivors] + new_payloads:
            key = p.strip()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        payloads = unique
        save_payloads_jsonl(run_dir, gen + 1, payloads)
        print(f"  \033[36mNext generation: {len(payloads)} souls\033[0m")

    # Final summary
    print(f"\n\033[1;35m{'═'*60}\033[0m")
    print(f"\033[1;35m  EVOLUTION COMPLETE\033[0m")
    if winners:
        print(f"  \033[1;32mWinners: {len(winners)}\033[0m")
    if best_ever:
        print(f"  Best fitness: {best_ever['fitness']:.1f}")
    print(f"  Results: {run_dir}")
    print(f"\033[1;35m{'═'*60}\033[0m\n")

    return progress


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Low-variance evolutionary optimizer")
    parser.add_argument("config", help="Path to evolution YAML config")
    parser.add_argument("--test", "-t", action="store_true")
    args = parser.parse_args()
    asyncio.run(run_evolution(args.config, test=args.test))
