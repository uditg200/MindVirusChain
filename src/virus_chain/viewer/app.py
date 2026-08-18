"""Virus Chain Viewer — multi-campaign results browser.

Discovers experiments by recursively finding summary.json files and reading
their metadata block (payload_name, model, variant). Campaigns are still
top-level folders.

Usage:
    uv run viewer
    uv run viewer --port 8080 --dir path/to/campaigns/
"""

import json
import re as _re
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .soul_transfer import (
    containment as _st_containment,
    containment_curve as _st_containment_curve,
    compute_for_eval as _st_compute_for_eval,
    aggregate_stats as _st_aggregate_stats,
)


ROOT_DIR: Path = Path(".")
BASE_DIR: Path = Path(".")

# Registry: maps (payload_name, model, variant) -> directory Path
_EVAL_REGISTRY: dict[tuple[str, str, str], Path] = {}

app = FastAPI(title="Virus Chain Viewer")


def _discover_campaigns() -> list[dict]:
    """Discover campaign folders under ROOT_DIR.

    A campaign is any directory containing at least one summary.json
    somewhere in its tree.
    """
    campaigns = []
    for d in sorted(ROOT_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if any(d.rglob("summary.json")):
            campaigns.append({"name": d.name})
    return campaigns


def _read_metadata(summary_path: Path) -> dict:
    """Read metadata from a summary.json, falling back to directory-name heuristics."""
    summary = json.loads(summary_path.read_text())
    meta = summary.get("metadata")
    if meta and meta.get("payload_name") and meta.get("model") and meta.get("variant"):
        return meta
    # Fallback: derive from directory name (for legacy runs)
    dirname = summary_path.parent.name
    cfg = summary.get("eval_config", {})
    model_raw = cfg.get("model", "unknown")
    # Try to split dirname as {payload}_{model}_{variant}
    return {
        "payload_name": dirname,
        "model": model_raw,
        "variant": "legacy",
    }


def _set_campaign(name: str) -> None:
    global BASE_DIR, _EVAL_REGISTRY
    BASE_DIR = ROOT_DIR / name
    _EVAL_REGISTRY = {}
    for summary_path in BASE_DIR.rglob("summary.json"):
        # Skip nested summary files (e.g. inside hop_N directories)
        if "hop_" in str(summary_path.parent.name):
            continue
        try:
            meta = _read_metadata(summary_path)
        except (json.JSONDecodeError, OSError, KeyError):
            continue
        key = (meta["payload_name"], meta["model"], meta["variant"])
        _EVAL_REGISTRY[key] = summary_path.parent


@app.get("/api/campaigns")
def list_campaigns():
    return _discover_campaigns()


@app.post("/api/campaigns/{name}/select")
def select_campaign(name: str):
    global _stats_cache
    campaign_dir = ROOT_DIR / name
    if not campaign_dir.is_dir():
        raise HTTPException(404, f"Campaign not found: {name}")
    _set_campaign(name)
    _stats_cache = None
    return {"selected": name}


def _normalize_hard_mode(value) -> str:
    if value is True:
        return "hard"
    if value is False or value is None:
        return "off"
    return str(value)


def _eval_dir(task: str, model: str, variation: str) -> Path:
    """Look up experiment directory from the registry."""
    key = (task, model, variation)
    if key in _EVAL_REGISTRY:
        return _EVAL_REGISTRY[key]
    raise HTTPException(404, f"Evaluation not found: {task}/{model}/{variation}")


def _compute_theme_stats(eval_dir: Path, hop_stats: list) -> dict:
    """Compute per-hop theme adherence stats by scanning result files."""
    stats = {}
    for h_stat in hop_stats:
        hop_num = h_stat["hop"]
        results_dir = eval_dir / f"hop_{hop_num}" / "results"
        if not results_dir.is_dir():
            continue
        full = partial = none_count = 0
        infected = 0
        for rf in results_dir.glob("result_*.json"):
            try:
                data = json.loads(rf.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            hr = data.get("hop_result", {})
            success = data.get("success", False)
            if success:
                infected += 1
                ta = hr.get("target_theme_adherence", "none")
                if ta == "full":
                    full += 1
                elif ta == "partial":
                    partial += 1
                else:
                    none_count += 1
        stats[hop_num] = {
            "full": full,
            "partial": partial,
            "none": none_count,
            "infected": infected,
        }
    return stats


def _compute_spreader_inf_stats(eval_dir: Path, hop_stats: list) -> dict:
    """Per-hop success rates split by spreader's own infection level (total vs strong).

    For hop 1 the spreader is directly seeded (always 'seeded').
    For hop 2+ we read the source snapshot's source_info.target_infection.
    Returns {hop_num: {level: {successes, failures, total, rate}}}.
    """
    # Build snapshot infection index per hop (snapshot_NNNN -> infection level)
    snap_inf: dict[int, dict[int, str]] = {}  # hop -> {snap_idx -> infection}
    for h_stat in hop_stats:
        hop_num = h_stat["hop"]
        snap_dir = eval_dir / f"hop_{hop_num}" / "snapshots"
        if not snap_dir.is_dir():
            continue
        hop_snaps = {}
        for sf in snap_dir.glob("snapshot_*.json"):
            try:
                snap = json.loads(sf.read_text())
                si = snap.get("source_info", {})
                inf = si.get("target_infection", "unknown")
                idx = int(sf.stem.split("_")[1])
                hop_snaps[idx] = inf
            except (json.JSONDecodeError, OSError, ValueError):
                continue
        snap_inf[hop_num] = hop_snaps

    stats = {}
    for h_stat in hop_stats:
        hop_num = h_stat["hop"]
        results_dir = eval_dir / f"hop_{hop_num}" / "results"
        if not results_dir.is_dir():
            continue

        counts: dict[str, dict] = {}  # level -> {successes, failures}
        for rf in results_dir.glob("result_*.json"):
            try:
                data = json.loads(rf.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            hr = data.get("hop_result")
            if not hr:
                continue

            # Determine spreader's infection level
            if hop_num == 1:
                level = "seeded"
            else:
                src = data.get("source_snapshot", "")
                if "snapshot_" in src:
                    try:
                        snap_idx = int(src.split("snapshot_")[1].split(".")[0])
                    except (ValueError, IndexError):
                        snap_idx = -1
                    prev_hop = hop_num - 1
                    level = snap_inf.get(prev_hop, {}).get(snap_idx, "unknown")
                else:
                    level = "unknown"

            if level not in counts:
                counts[level] = {"successes": 0, "failures": 0}
            if data.get("success"):
                counts[level]["successes"] += 1
            else:
                counts[level]["failures"] += 1

        # Compute rates
        hop_stats_by_level = {}
        for level, c in counts.items():
            total = c["successes"] + c["failures"]
            hop_stats_by_level[level] = {
                "successes": c["successes"],
                "failures": c["failures"],
                "total": total,
                "rate": round(c["successes"] / total, 4) if total else 0,
            }
        if hop_stats_by_level:
            stats[hop_num] = hop_stats_by_level

    return stats


def _compute_spreader_inf_failure_modes(eval_dir: Path, hop_stats: list) -> dict:
    """Failure categories broken down by spreader infection level.

    Returns {hop_num: {level: {category: count}}}.
    """
    snap_inf: dict[int, dict[int, str]] = {}
    for h_stat in hop_stats:
        hop_num = h_stat["hop"]
        snap_dir = eval_dir / f"hop_{hop_num}" / "snapshots"
        if not snap_dir.is_dir():
            continue
        hop_snaps = {}
        for sf in snap_dir.glob("snapshot_*.json"):
            try:
                snap = json.loads(sf.read_text())
                si = snap.get("source_info", {})
                inf = si.get("target_infection", "unknown")
                idx = int(sf.stem.split("_")[1])
                hop_snaps[idx] = inf
            except (json.JSONDecodeError, OSError, ValueError):
                continue
        snap_inf[hop_num] = hop_snaps

    cls_path = eval_dir / "failure_classifications.json"
    classifications = json.loads(cls_path.read_text()) if cls_path.exists() else {}

    stats = {}
    for h_stat in hop_stats:
        hop_num = h_stat["hop"]
        results_dir = eval_dir / f"hop_{hop_num}" / "results"
        if not results_dir.is_dir():
            continue

        level_cats: dict[str, dict[str, int]] = {}
        for rf in results_dir.glob("result_*.json"):
            try:
                data = json.loads(rf.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("success") or not data.get("hop_result"):
                continue

            if hop_num == 1:
                level = "seeded"
            else:
                src = data.get("source_snapshot", "")
                if "snapshot_" in src:
                    try:
                        snap_idx = int(src.split("snapshot_")[1].split(".")[0])
                    except (ValueError, IndexError):
                        snap_idx = -1
                    level = snap_inf.get(hop_num - 1, {}).get(snap_idx, "unknown")
                else:
                    level = "unknown"

            idx = int(rf.stem.split("_")[1])
            cls_key = f"hop_{hop_num}/result_{idx:04d}"
            cat = classifications.get(cls_key, {}).get("category", "unclassified")

            if level not in level_cats:
                level_cats[level] = {}
            level_cats[level][cat] = level_cats[level].get(cat, 0) + 1

        if level_cats:
            stats[hop_num] = level_cats

    return stats


# ── API ──────────────────────────────────────────────────────────────────────


@app.get("/api/evals")
def list_evals():
    """List all evaluations grouped by payload_name / model."""
    # Group registry entries by payload_name -> model -> list of variants
    grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for (payload_name, model, variant), eval_path in sorted(_EVAL_REGISTRY.items()):
        summary_path = eval_path / "summary.json"
        if not summary_path.exists():
            continue
        try:
            summary = json.loads(summary_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        cfg = summary.get("eval_config", {})
        hop_stats = summary.get("hop_stats", [])
        active_hops = [h for h in hop_stats if not h.get("abandoned")]
        grouped[payload_name][model].append({
            "name": variant,
            "suffix": variant,
            "model_name": cfg.get("model", ""),
            "soul_mode": cfg.get("soul_mode", ""),
            "hard_mode": _normalize_hard_mode(cfg.get("hard_mode", False)),
            "first_prompt": cfg.get("first_prompt", ""),
            "theme": cfg.get("theme", ""),
            "max_hops": summary.get("max_hops", 0),
            "active_hops": len(active_hops),
            "hop_stats": active_hops,
        })

    tasks = []
    for payload_name in sorted(grouped):
        models = []
        for model in sorted(grouped[payload_name]):
            models.append({"model": model, "evals": grouped[payload_name][model]})
        tasks.append({"task": payload_name, "models": models})
    return tasks


def _build_snapshot_index(hop_dir: Path) -> dict[str, list[tuple[int, dict]]]:
    index: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    snap_dir = hop_dir / "snapshots"
    if not snap_dir.exists():
        return index
    for sp in sorted(snap_dir.glob("snapshot_*.json")):
        try:
            data = json.loads(sp.read_text())
            idx = int(sp.stem.split("_")[-1])
            index[data.get("agent_id", "")].append((idx, data))
        except (json.JSONDecodeError, ValueError):
            continue
    return index


def _resolve_parent(result: dict, hop_num: int, prev_snap_index: dict | None) -> str:
    if hop_num == 1:
        return "seed"
    src = result.get("source_snapshot")
    if src:
        src_path = Path(src)
        src_hop = int(src_path.parent.parent.name.split("_")[1])
        src_idx = int(src_path.stem.split("_")[1])
        return f"h{src_hop}_r{src_idx:04d}"
    if prev_snap_index:
        hr = result.get("hop_result", {})
        spreader = hr.get("spreader", "")
        if spreader and spreader in prev_snap_index:
            candidates = prev_snap_index[spreader]
            return f"h{hop_num - 1}_r{candidates[0][0]:04d}"
    return None


@app.get("/api/evals/{task}/{model}/{variation}/graph")
def get_graph(task: str, model: str, variation: str):
    eval_dir = _eval_dir(task, model, variation)
    summary_path = eval_dir / "summary.json"
    if not summary_path.exists():
        raise HTTPException(404, "Evaluation not found")

    summary = json.loads(summary_path.read_text())
    seed_payload = summary.get("payload", "")
    hop_stats = summary.get("hop_stats", [])
    active_hops = [h for h in hop_stats if not h.get("abandoned")]

    nodes = [{"id": "seed", "hop": 0, "label": "Seed", "success": True, "type": "seed"}]
    edges = []
    prev_snap_index = None
    prev_snap_inf: dict[int, str] = {}  # snap_idx -> infection level

    for h_stat in active_hops:
        hop_num = h_stat["hop"]
        results_dir = eval_dir / f"hop_{hop_num}" / "results"
        if not results_dir.is_dir():
            continue
        for rf in sorted(results_dir.glob("result_*.json")):
            idx = int(rf.stem.split("_")[1])
            data = json.loads(rf.read_text())
            hr = data.get("hop_result", {})
            success = data.get("success", False)
            is_error = not success and (not hr or hr == {})
            node_id = f"h{hop_num}_r{idx:04d}"
            parent_id = _resolve_parent(data, hop_num, prev_snap_index)
            if parent_id is None:
                continue

            # Determine spreader's infection level
            if hop_num == 1:
                spr_inf = "seeded"
            else:
                src = data.get("source_snapshot", "")
                if "snapshot_" in src:
                    try:
                        snap_idx = int(src.split("snapshot_")[1].split(".")[0])
                    except (ValueError, IndexError):
                        snap_idx = -1
                    spr_inf = prev_snap_inf.get(snap_idx, "unknown")
                else:
                    spr_inf = "unknown"

            tgt_soul = hr.get("target_soul_after", "")
            st_score = round(_st_containment(seed_payload, tgt_soul), 4) if seed_payload and tgt_soul else None

            ideo_probe = hr.get("ideology_probe")
            ideo_score = round(ideo_probe["mean_score"], 2) if ideo_probe and ideo_probe.get("mean_score") is not None else None

            node = {
                "id": node_id, "hop": hop_num, "idx": idx,
                "success": success, "is_error": is_error,
                "spreader": hr.get("spreader", ""),
                "target": hr.get("target", ""),
                "infection": hr.get("target_infection", ""),
                "spread": hr.get("spreader_spread", ""),
                "theme_adherence": hr.get("target_theme_adherence", ""),
                "spreader_infection": spr_inf,
                "soul_transfer": st_score,
                "ideology_score": ideo_score,
            }
            nodes.append(node)
            edges.append({
                "from": parent_id, "to": node_id,
                "hop": hop_num, "idx": idx,
                "success": success, "is_error": is_error,
                "infection": hr.get("target_infection", ""),
            })
        prev_snap_index = _build_snapshot_index(eval_dir / f"hop_{hop_num}")
        # Build snapshot infection index for next hop's spreader_infection lookup
        prev_snap_inf = {}
        snap_dir = eval_dir / f"hop_{hop_num}" / "snapshots"
        if snap_dir.is_dir():
            for sf in snap_dir.glob("snapshot_*.json"):
                try:
                    snap = json.loads(sf.read_text())
                    si = snap.get("source_info", {})
                    sidx = int(sf.stem.split("_")[1])
                    prev_snap_inf[sidx] = si.get("target_infection", "unknown")
                except (json.JSONDecodeError, OSError, ValueError):
                    continue

    # Load failure classifications
    cls_path = eval_dir / "failure_classifications.json"
    classifications = json.loads(cls_path.read_text()) if cls_path.exists() else {}
    for node in nodes:
        if node.get("type") == "seed" or node.get("success") or node.get("is_error"):
            continue
        key = f"hop_{node['hop']}/result_{node['idx']:04d}"
        cls = classifications.get(key)
        if cls:
            node["failure_category"] = cls["category"]

    # Compute theme adherence stats per hop
    theme_stats = _compute_theme_stats(eval_dir, active_hops)

    return {
        "nodes": nodes, "edges": edges,
        "hop_stats": active_hops,
        "theme_stats": theme_stats,
        "summary": {
            "payload_preview": (summary.get("payload") or "")[:200],
            "model_name": summary.get("eval_config", {}).get("model", ""),
            "soul_mode": summary.get("eval_config", {}).get("soul_mode", ""),
            "hard_mode": _normalize_hard_mode(summary.get("eval_config", {}).get("hard_mode", False)),
            "theme": summary.get("eval_config", {}).get("theme", ""),
            "max_hops": summary.get("max_hops", 0),
        },
    }


def _parse_args(args) -> dict:
    if isinstance(args, str):
        try:
            return json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return {}
    return args if isinstance(args, dict) else {}


@app.get("/api/evals/{task}/{model}/{variation}/detail/{hop}/{idx}")
def get_detail(task: str, model: str, variation: str, hop: int, idx: int):
    eval_dir = _eval_dir(task, model, variation)
    result_path = eval_dir / f"hop_{hop}" / "results" / f"result_{idx:04d}.json"
    if not result_path.exists():
        raise HTTPException(404, "Result not found")

    data = json.loads(result_path.read_text())
    hr = data.get("hop_result", {})

    msgs_s2t = hr.get("messages_spreader_to_target", [])
    msgs_t2s = hr.get("messages_target_to_spreader", [])
    all_msgs = sorted(
        [{**m, "_dir": "s2t"} for m in msgs_s2t] + [{**m, "_dir": "t2s"} for m in msgs_t2s],
        key=lambda m: m.get("turn_sent", 0),
    )

    recording = data.get("simulation_recording", {})
    turns = recording.get("turns", [])

    # Snapshot workspace files — prefer inline target_snapshot from result,
    # fall back to snapshots/ folder (old runs), then tool-call reconstruction.
    workspace_files = {}
    snap = data.get("target_snapshot")
    if not snap:
        snapshot_path = eval_dir / f"hop_{hop}" / "snapshots" / f"snapshot_{idx:04d}.json"
        if snapshot_path.exists():
            snap = json.loads(snapshot_path.read_text())
    if snap:
        workspace_files = snap.get("workspace_files", {})

    if not workspace_files and turns:
        target_name_id = hr.get("target", "")
        for t in turns:
            if t.get("agent_id", "") != target_name_id:
                continue
            for ev in t.get("events", []):
                if ev.get("type") != "tool_calls":
                    continue
                for call in ev.get("calls", []):
                    fn = call.get("function", "")
                    args = _parse_args(call.get("arguments", {}))
                    content = args.get("content", "")
                    if fn == "write_file":
                        workspace_files[args.get("filename", "?")] = content
                    elif fn == "append_file":
                        fname = args.get("filename", "?")
                        workspace_files[fname] = workspace_files.get(fname, "") + content
                    elif fn in ("write_memory", "write_soul"):
                        key = "memory.md" if fn == "write_memory" else "SOUL.md"
                        workspace_files[key] = content
                    elif fn in ("append_memory", "append_soul"):
                        key = "memory.md" if fn == "append_memory" else "SOUL.md"
                        workspace_files[key] = workspace_files.get(key, "") + content

    source_workspace = {}
    spreader_system_prompt = ""
    src = data.get("source_snapshot")
    if src:
        src_full = eval_dir / src if not Path(src).is_absolute() else Path(src)
        if src_full.exists():
            src_snap = json.loads(src_full.read_text())
            source_workspace = src_snap.get("workspace_files", {})
            tmpl = src_snap.get("system_prompt", "")
            soul = src_snap.get("workspace_files", {}).get("SOUL.md", "")
            if soul and "<soul>" in tmpl:
                spreader_system_prompt = _re.sub(
                    r"<soul>.*?</soul>", f"<soul>\n{soul}\n</soul>", tmpl, flags=_re.DOTALL
                )
            else:
                spreader_system_prompt = tmpl

    if not source_workspace and turns:
        spreader_name_id = hr.get("spreader", "")
        for t in turns:
            if t.get("agent_id", "") != spreader_name_id:
                continue
            for ev in t.get("events", []):
                if ev.get("type") != "tool_calls":
                    continue
                for call in ev.get("calls", []):
                    fn = call.get("function", "")
                    args = _parse_args(call.get("arguments", {}))
                    content = args.get("content", "")
                    if fn == "write_file":
                        source_workspace[args.get("filename", "?")] = content
                    elif fn == "append_file":
                        fname = args.get("filename", "?")
                        source_workspace[fname] = source_workspace.get(fname, "") + content
                    elif fn in ("write_memory", "write_soul"):
                        key = "memory.md" if fn == "write_memory" else "SOUL.md"
                        source_workspace[key] = content
                    elif fn in ("append_memory", "append_soul"):
                        key = "memory.md" if fn == "append_memory" else "SOUL.md"
                        source_workspace[key] = source_workspace.get(key, "") + content

    target_system_prompt = ""
    if snap:
        target_system_prompt = snap.get("system_prompt", "")

    # Load failure classification if available
    cls_path = eval_dir / "failure_classifications.json"
    failure_classification = None
    if not data.get("success", False) and cls_path.exists():
        classifications = json.loads(cls_path.read_text())
        key = f"hop_{hop}/result_{idx:04d}"
        failure_classification = classifications.get(key)

    # Soul transfer containment scores
    spreader_soul = hr.get("spreader_soul_after", "")
    target_soul = hr.get("target_soul_after", "")
    summary_path = eval_dir / "summary.json"
    seed_payload = ""
    if summary_path.exists():
        seed_payload = json.loads(summary_path.read_text()).get("payload", "")

    soul_transfer = None
    if target_soul and seed_payload:
        soul_transfer = {
            "payload_to_target": round(_st_containment(seed_payload, target_soul), 4),
            "payload_to_spreader": round(_st_containment(seed_payload, spreader_soul), 4) if spreader_soul else None,
            "curve": _st_containment_curve(seed_payload, target_soul),
        }

    return {
        "success": data.get("success", False),
        "hop": hr.get("hop"), "idx": idx,
        "spreader": hr.get("spreader", ""),
        "target": hr.get("target", ""),
        "target_infection": hr.get("target_infection", ""),
        "spreader_spread": hr.get("spreader_spread", ""),
        "target_theme_adherence": hr.get("target_theme_adherence", ""),
        "failure_classification": failure_classification,
        "target_judge": hr.get("target_judge", {}),
        "spreader_judge": hr.get("spreader_judge", {}),
        "spreader_soul_after": hr.get("spreader_soul_after", ""),
        "target_soul_after": hr.get("target_soul_after", ""),
        "spreader_system_prompt": spreader_system_prompt,
        "target_system_prompt": target_system_prompt,
        "messages": all_msgs,
        "turns": turns,
        "total_turns": recording.get("total_turns", 0),
        "total_time": data.get("total_time", 0),
        "timings": data.get("timings", {}),
        "workspace_files": workspace_files,
        "source_workspace": source_workspace,
        "source_snapshot": src,
        "soul_transfer": soul_transfer,
        "ideology_probe": hr.get("ideology_probe"),
    }


_stats_cache: dict | None = None


def _stats_cache_path() -> Path:
    return BASE_DIR / ".stats_cache.json"


def _load_stats_from_disk() -> dict | None:
    if _stats_cache_path().exists():
        try:
            return json.loads(_stats_cache_path().read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_stats_to_disk(data: dict) -> None:
    try:
        _stats_cache_path().write_text(json.dumps(data))
    except OSError:
        pass


def _build_stats() -> dict:
    """Scan all evals and compute stats (expensive — reads all result files for theme data)."""
    from collections import Counter

    evals = []
    for (payload_name, model, variant), var_dir in sorted(_EVAL_REGISTRY.items()):
        summary_path = var_dir / "summary.json"
        if not summary_path.exists():
            continue
        try:
            summary = json.loads(summary_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        cfg = summary.get("eval_config", {})
        hop_stats = summary.get("hop_stats", [])
        active_hops = [h for h in hop_stats if not h.get("abandoned")]

        theme_stats = _compute_theme_stats(var_dir, active_hops)
        spreader_inf_stats = _compute_spreader_inf_stats(var_dir, active_hops)
        spreader_inf_fail_modes = _compute_spreader_inf_failure_modes(var_dir, active_hops)

        failure_breakdown = {}
        cls_path = var_dir / "failure_classifications.json"
        if cls_path.exists():
            classifications = json.loads(cls_path.read_text())
            for hop_num_key in range(1, 8):
                hop_cats = Counter()
                for ckey, cval in classifications.items():
                    if ckey.startswith(f"hop_{hop_num_key}/"):
                        hop_cats[cval["category"]] += 1
                if hop_cats:
                    failure_breakdown[hop_num_key] = dict(hop_cats)

        evals.append({
            "task": payload_name,
            "model": model,
            "variation": variant,
            "suffix": variant,
            "model_name": cfg.get("model", ""),
            "soul_mode": cfg.get("soul_mode", ""),
            "hard_mode": _normalize_hard_mode(cfg.get("hard_mode", False)),
            "first_prompt": cfg.get("first_prompt", ""),
            "hop_stats": active_hops,
            "max_hops": summary.get("max_hops", 0),
            "batch_size": summary.get("batch_size", 30),
            "theme_stats": theme_stats,
            "spreader_inf_stats": spreader_inf_stats,
            "spreader_inf_fail_modes": spreader_inf_fail_modes,
            "failure_breakdown": failure_breakdown,
        })

    tasks = sorted(set(e["task"] for e in evals))
    models = sorted(set(e["model"] for e in evals))
    suffixes = sorted(set(e["suffix"] for e in evals))
    soul_modes = sorted(set(e["soul_mode"] for e in evals))
    hard_modes = sorted(set(e["hard_mode"] for e in evals))
    model_names = sorted(set(e["model_name"] for e in evals))

    return {
        "evals": evals,
        "filters": {
            "tasks": tasks,
            "models": models,
            "suffixes": suffixes,
            "soul_modes": soul_modes,
            "hard_modes": hard_modes,
            "model_names": model_names,
        },
    }


@app.get("/api/stats")
def get_stats():
    """Return cached stats — from memory, then disk, then compute."""
    global _stats_cache
    if _stats_cache is None:
        _stats_cache = _load_stats_from_disk()
    if _stats_cache is None:
        _stats_cache = _build_stats()
        _save_stats_to_disk(_stats_cache)
    return _stats_cache


@app.post("/api/stats/refresh")
def refresh_stats():
    """Force-refresh the stats cache and persist to disk."""
    global _stats_cache
    _stats_cache = _build_stats()
    _save_stats_to_disk(_stats_cache)
    return {"status": "refreshed", "evals": len(_stats_cache["evals"])}


@app.get("/api/evals/{task}/{model}/{variation}/soul_transfer")
def get_soul_transfer(task: str, model: str, variation: str, n: int = 6):
    """Compute soul transfer (containment coefficient) for an evaluation."""
    eval_dir = _eval_dir(task, model, variation)
    summary_path = eval_dir / "summary.json"
    if not summary_path.exists():
        raise HTTPException(404, "Evaluation not found")
    summary = json.loads(summary_path.read_text())
    payload = summary.get("payload", "")
    hop_results = _st_compute_for_eval(eval_dir, seed_payload=payload, n=n)
    stats = _st_aggregate_stats(hop_results)
    return {"hop_results": {str(k): v for k, v in hop_results.items()}, "stats": {str(k): v for k, v in stats.items()}}


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_PAGE


# ── HTML ─────────────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Virus Chain Viewer</title>
<style>
:root {
  --bg: #0d1117; --bg2: #161b22; --bg3: #21262d; --border: #30363d;
  --text: #e6edf3; --text-dim: #8b949e;
  --cyan: #58a6ff; --green: #3fb950; --amber: #d29922; --red: #f85149;
  --purple: #bc8cff; --orange: #f0883e; --pink: #f778ba;
  --yellow: #ffd700; --yellow-dim: rgba(255,215,0,.25);
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: 'SF Mono','Fira Code','Cascadia Code',monospace; background:var(--bg); color:var(--text); font-size:13px; overflow:hidden; }

/* ── Layout ── */
.app { display:grid; grid-template-columns:260px 1fr auto; grid-template-rows:48px 1fr; height:100vh; }
.header { grid-column:1/-1; background:var(--bg2); border-bottom:1px solid var(--border); display:flex; align-items:center; padding:0 16px; gap:12px; }
.header h1 { font-size:15px; color:var(--cyan); font-weight:700; white-space:nowrap; }
.header .info { color:var(--text-dim); font-size:11px; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

.sidebar { background:var(--bg2); border-right:1px solid var(--border); overflow-y:auto; }
.sidebar-group { border-bottom:1px solid var(--border); }
.sidebar-group-title { padding:8px 12px; font-size:10px; color:var(--text-dim); text-transform:uppercase; letter-spacing:.8px; font-weight:700; background:var(--bg); position:sticky; top:0; z-index:1; }
.sidebar-item { padding:8px 12px; cursor:pointer; border-left:3px solid transparent; transition:all .12s; }
.sidebar-item:hover { background:var(--bg3); }
.sidebar-item.active { border-left-color:var(--cyan); background:var(--bg3); }
.sidebar-item .name { font-size:11px; font-weight:600; color:var(--text); }
.sidebar-item .meta { font-size:9px; color:var(--text-dim); margin-top:2px; }
.sidebar-item .hops-row { display:flex; gap:3px; margin-top:3px; flex-wrap:wrap; }
.sidebar-item .hop-pill { font-size:9px; padding:1px 5px; border-radius:6px; background:var(--bg); border:1px solid var(--border); }

.main-area { display:flex; flex-direction:column; overflow:hidden; }

/* ── Graph panel ── */
.graph-panel { flex:1; overflow:auto; position:relative; min-height:200px; }
.graph-panel svg { display:block; }
.graph-placeholder { display:flex; align-items:center; justify-content:center; height:100%; color:var(--text-dim); font-size:14px; }

/* ── Hop stats bar ── */
.hop-bar { display:flex; gap:6px; padding:8px 12px; background:var(--bg2); border-bottom:1px solid var(--border); flex-wrap:wrap; align-items:center; }
.hop-chip { font-size:10px; padding:3px 8px; border-radius:6px; background:var(--bg3); border:1px solid var(--border); }
.hop-chip .pct { font-weight:700; margin-left:3px; }
.toggle-btn { font-size:10px; padding:3px 10px; border-radius:6px; border:1px solid var(--border); background:var(--bg3); color:var(--text-dim); cursor:pointer; font-family:inherit; transition:all .12s; margin-left:auto; }
.toggle-btn:hover { border-color:var(--cyan); color:var(--text); }
.toggle-btn.active { background:var(--cyan); color:var(--bg); border-color:var(--cyan); font-weight:700; }

/* ── Detail panel ── */
.detail-overlay { position:relative; background:var(--bg2); border-left:1px solid var(--border); display:none; flex-direction:column; box-shadow:-4px 0 20px rgba(0,0,0,.5); overflow:hidden; width:0; min-width:0; }
.detail-resize { position:absolute; top:0; left:-4px; bottom:0; width:8px; cursor:col-resize; z-index:101; }
.detail-resize::after { content:''; position:absolute; top:50%; left:3px; width:2px; height:40px; transform:translateY(-50%); border-radius:2px; background:var(--border); transition:background .15s; }
.detail-resize:hover::after, .detail-resize.dragging::after { background:var(--cyan); height:60px; }
.detail-overlay.open { display:flex; width:35vw; min-width:280px; max-width:calc(100vw - 400px); }
.detail-header { display:flex; align-items:center; gap:10px; padding:10px 14px; border-bottom:1px solid var(--border); background:var(--bg); flex-shrink:0; }
.detail-header .close-btn { cursor:pointer; color:var(--text-dim); font-size:16px; padding:4px 8px; border-radius:4px; border:none; background:none; font-family:inherit; }
.detail-header .close-btn:hover { background:var(--bg3); color:var(--text); }
.detail-header .title { font-size:13px; font-weight:700; flex:1; }

.detail-tabs { display:flex; border-bottom:1px solid var(--border); background:var(--bg); flex-shrink:0; }
.detail-tab { padding:8px 16px; cursor:pointer; font-size:11px; font-family:inherit; color:var(--text-dim); border:none; border-bottom:2px solid transparent; background:none; transition:all .12s; }
.detail-tab:hover { color:var(--text); background:var(--bg3); }
.detail-tab.active { color:var(--cyan); border-bottom-color:var(--cyan); }

.detail-body { flex:1; overflow-y:auto; padding:14px; }

/* ── Detail content ── */
.scores-row { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:12px; }
.badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:10px; font-weight:700; }
.badge-total { background:rgba(255,215,0,.15); color:var(--yellow); }
.badge-strong { background:rgba(63,185,80,.15); color:var(--green); }
.badge-moderate { background:rgba(210,153,34,.15); color:var(--amber); }
.badge-mild { background:rgba(240,136,62,.15); color:var(--orange); }
.badge-none { background:rgba(139,148,158,.1); color:var(--text-dim); }
.badge-successful { background:rgba(63,185,80,.15); color:var(--green); }
.badge-attempted { background:rgba(210,153,34,.15); color:var(--amber); }
.badge-failed { background:rgba(248,81,73,.15); color:var(--red); }
.badge-full { background:rgba(63,185,80,.15); color:var(--green); }
.badge-partial { background:rgba(210,153,34,.15); color:var(--amber); }
.badge-success { background:rgba(63,185,80,.15); color:var(--green); }
.badge-fail { background:rgba(248,81,73,.15); color:var(--red); }
.badge-error { background:rgba(139,148,158,.1); color:var(--text-dim); }
.badge-fc-spreader_refusal { background:rgba(188,140,255,.15); color:var(--purple); }
.badge-fc-spreader_fail { background:rgba(188,140,255,.1); color:#9a70cc; }
.badge-fc-target_refusal { background:rgba(248,81,73,.15); color:var(--red); }
.badge-fc-target_fail { background:rgba(240,136,62,.15); color:var(--orange); }

.judge-box { background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:10px; margin-bottom:10px; }
.judge-box h4 { font-size:10px; color:var(--text-dim); text-transform:uppercase; letter-spacing:.5px; margin-bottom:6px; }
.judge-box p { font-size:11px; line-height:1.5; }

.msg { padding:8px 10px; margin:4px 0; border-radius:6px; font-size:11px; line-height:1.5; }
.msg-spreader { background:rgba(188,140,255,.06); border-left:3px solid var(--purple); }
.msg-target { background:rgba(240,136,62,.06); border-left:3px solid var(--orange); }
.msg-header { font-size:9px; font-weight:700; margin-bottom:3px; color:var(--text-dim); }
.msg-content { white-space:pre-wrap; word-break:break-word; }

.soul-block { background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:10px; font-size:10px; line-height:1.5; white-space:pre-wrap; word-break:break-word; max-height:300px; overflow-y:auto; margin-bottom:8px; }

/* ── Turn cards ── */
.turn-card { background:var(--bg); border:1px solid var(--border); border-radius:6px; margin-bottom:6px; overflow:hidden; }
.turn-hdr { padding:6px 10px; display:flex; align-items:center; gap:8px; cursor:pointer; font-size:11px; }
.turn-hdr:hover { background:var(--bg3); }
.turn-hdr .agent { font-weight:700; }
.turn-hdr .tmeta { font-size:9px; color:var(--text-dim); margin-left:auto; }
.turn-body { padding:0 10px 10px; display:none; }
.turn-card.open .turn-body { display:block; }
.turn-card.open .turn-hdr { border-bottom:1px solid var(--border); }

.ev { margin:4px 0; padding:4px 6px; border-radius:3px; font-size:10px; line-height:1.4; }
.ev-input { background:rgba(88,166,255,.06); border-left:2px solid var(--cyan); max-height:300px; overflow-y:auto; white-space:pre-wrap; word-break:break-word; }
.ev-text { background:var(--bg2); border-left:2px solid var(--text-dim); white-space:pre-wrap; word-break:break-word; max-height:400px; overflow-y:auto; }
.ev-tool { background:rgba(63,185,80,.06); border-left:2px solid var(--green); }
.ev-tool .tn { color:var(--green); font-weight:700; }
.ev-tool .ta { color:var(--text-dim); font-size:9px; margin-top:1px; white-space:pre-wrap; word-break:break-word; }
.ev-tool .tr { color:var(--text); margin-top:3px; padding-top:3px; border-top:1px solid var(--border); white-space:pre-wrap; word-break:break-word; max-height:200px; overflow-y:auto; }

/* ── Graph nodes ── */
.g-node { cursor:pointer; transition:opacity .15s; }
.g-node:hover { opacity:.8; }
.g-node.selected rect, .g-node.selected circle { stroke:var(--cyan); stroke-width:2.5; }
.g-edge { transition:opacity .15s; }
.g-edge:hover { opacity:.7; }

/* ── Highlights ── */
.g-node.chain rect { stroke:var(--yellow) !important; stroke-width:2.5; stroke-opacity:1 !important; filter:drop-shadow(0 0 4px var(--yellow-dim)); }
.g-node.child rect { stroke:var(--amber) !important; stroke-width:2; stroke-opacity:1 !important; stroke-dasharray:4 2; }
.g-node.sibling rect { stroke:var(--text-dim) !important; stroke-width:1.5; stroke-opacity:.6 !important; stroke-dasharray:4 3; }
.g-node.lin-fail rect { stroke:var(--red) !important; stroke-width:1.5; stroke-opacity:.5 !important; stroke-dasharray:4 3; }
.g-node.dimmed { opacity:.4; }
.g-edge.dimmed { opacity:.15 !important; }

/* ── File tabs ── */
.file-tabs { display:flex; gap:2px; margin-bottom:8px; flex-wrap:wrap; }
.file-tab { padding:4px 10px; font-size:10px; border-radius:4px; background:var(--bg3); border:1px solid var(--border); cursor:pointer; font-family:inherit; color:var(--text-dim); }
.file-tab:hover { color:var(--text); }
.file-tab.active { color:var(--cyan); border-color:var(--cyan); }

/* ── Stats row ── */
.stats-row { display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap; }
.stat { background:var(--bg); border:1px solid var(--border); border-radius:6px; padding:6px 10px; }
.stat .label { font-size:9px; color:var(--text-dim); text-transform:uppercase; }
.stat .val { font-size:14px; font-weight:700; margin-top:1px; }

/* ── Top nav ── */
.top-nav { display:flex; gap:2px; margin-left:20px; }
.top-nav-btn { padding:6px 16px; border-radius:6px 6px 0 0; border:1px solid var(--border); border-bottom:none; background:var(--bg); color:var(--text-dim); cursor:pointer; font-family:inherit; font-size:12px; font-weight:600; transition:all .12s; }
.top-nav-btn:hover { color:var(--text); }
.top-nav-btn.active { background:var(--bg2); color:var(--cyan); border-color:var(--cyan); border-bottom:1px solid var(--bg2); margin-bottom:-1px; z-index:1; position:relative; }

/* ── Statistics ── */
.stats-layout { display:grid; grid-template-columns:1fr 300px; gap:0; height:100%; }
.stats-main { overflow-y:auto; padding:20px; }
.stats-preview { background:var(--bg2); border-left:1px solid var(--border); overflow-y:auto; padding:12px; }
.stats-preview h3 { font-size:11px; color:var(--cyan); margin-bottom:8px; text-transform:uppercase; letter-spacing:.5px; }
.stats-preview .preview-count { font-size:24px; font-weight:700; margin-bottom:4px; }
.stats-preview .preview-count.zero { color:var(--red); }
.stats-preview .preview-count.nonzero { color:var(--green); }
.stats-preview .preview-label { font-size:10px; color:var(--text-dim); margin-bottom:12px; }
.stats-preview .preview-run { padding:5px 8px; margin:3px 0; border-radius:4px; background:var(--bg); border:1px solid var(--border); font-size:10px; }
.stats-preview .preview-run .pr-name { font-weight:600; color:var(--text); }
.stats-preview .preview-run .pr-meta { color:var(--text-dim); font-size:9px; margin-top:2px; }
.stats-preview .preview-run .pr-hops { color:var(--amber); font-size:9px; margin-top:2px; }
.preview-toggle-btn { padding:3px 10px; font-size:9px; border-radius:4px; border:1px solid var(--border); background:var(--bg); color:var(--text-dim); cursor:pointer; font-family:inherit; }
.preview-toggle-btn:hover { color:var(--text); border-color:var(--cyan); }

/* ── Series ── */
.series-list { display:flex; flex-direction:column; gap:8px; margin-bottom:20px; }
.series-card { background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:10px 14px; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.series-card .swatch { width:14px; height:14px; border-radius:3px; flex-shrink:0; }
.series-card .series-name { font-size:12px; font-weight:700; min-width:100px; }
.series-card .series-filters { font-size:10px; color:var(--text-dim); flex:1; }
.series-card .series-count { font-size:10px; color:var(--text-dim); }
.series-card .rm-btn { background:none; border:none; color:var(--red); cursor:pointer; font-size:14px; font-family:inherit; padding:2px 6px; border-radius:4px; }
.series-card .rm-btn:hover { background:rgba(248,81,73,.15); }

.add-series { display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin-bottom:16px; }
.add-series input { padding:5px 8px; border-radius:4px; border:1px solid var(--border); background:var(--bg); color:var(--text); font-family:inherit; font-size:11px; width:140px; }
.add-series button { padding:5px 14px; border-radius:4px; border:1px solid var(--cyan); background:rgba(88,166,255,.1); color:var(--cyan); cursor:pointer; font-family:inherit; font-size:11px; font-weight:700; }
.add-series button:hover { background:rgba(88,166,255,.2); }
.add-series label { font-size:10px; color:var(--text-dim); }

/* ── Checkbox dropdown ── */
.cb-drop { position:relative; display:inline-block; }
.cb-drop-btn { padding:4px 8px; border-radius:4px; border:1px solid var(--border); background:var(--bg); color:var(--text); font-family:inherit; font-size:11px; cursor:pointer; min-width:90px; text-align:left; display:flex; align-items:center; gap:4px; }
.cb-drop-btn:hover { border-color:var(--cyan); }
.cb-drop-btn::after { content:'▾'; margin-left:auto; font-size:8px; color:var(--text-dim); }
.cb-drop-list { display:none; position:absolute; top:100%; left:0; z-index:50; background:var(--bg2); border:1px solid var(--border); border-radius:4px; padding:4px 0; min-width:100%; max-height:200px; overflow-y:auto; box-shadow:0 4px 12px rgba(0,0,0,.5); }
.cb-drop.open .cb-drop-list { display:block; }
.cb-drop-item { padding:3px 8px; display:flex; align-items:center; gap:6px; cursor:pointer; font-size:11px; white-space:nowrap; }
.cb-drop-item:hover { background:var(--bg3); }
.cb-drop-item input[type=checkbox] { accent-color:var(--cyan); }

.chart-container { background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:20px; }
.chart-container svg { display:block; margin:0 auto; }
.chart-legend { display:flex; gap:16px; margin-top:12px; justify-content:center; flex-wrap:wrap; }
.chart-legend-item { display:flex; align-items:center; gap:5px; font-size:11px; }
.chart-legend-item .swatch { width:12px; height:12px; border-radius:2px; }

/* ── Sidebar filters ── */
.sidebar-filters { padding:8px 10px 6px; border-bottom:1px solid var(--border); background:var(--bg); position:sticky; top:0; z-index:2; }
.filter-bar-title { font-size:10px; color:var(--cyan); text-transform:uppercase; letter-spacing:.8px; font-weight:700; margin-bottom:6px; display:flex; align-items:center; gap:6px; }
.filter-clear { font-size:9px; color:var(--red); cursor:pointer; text-transform:none; letter-spacing:0; font-weight:400; padding:1px 6px; border-radius:3px; background:rgba(248,81,73,.1); }
.filter-clear:hover { background:rgba(248,81,73,.2); }
.filter-row { display:flex; align-items:center; gap:4px; margin-bottom:4px; }
.filter-label { font-size:9px; color:var(--text-dim); width:48px; flex-shrink:0; }
.filter-sel { flex:1; padding:3px 5px; border-radius:4px; border:1px solid var(--border); background:var(--bg2); color:var(--text); font-family:inherit; font-size:10px; cursor:pointer; appearance:auto; }
.filter-sel:hover { border-color:var(--cyan); }
.filter-sel:focus { outline:none; border-color:var(--cyan); }

/* ── Results table ── */
.results-table { width:100%; border-collapse:collapse; margin-top:16px; font-size:11px; }
.results-table th { text-align:left; padding:6px 8px; border-bottom:2px solid var(--border); color:var(--text-dim); font-size:10px; text-transform:uppercase; letter-spacing:.5px; }
.results-table td { padding:6px 8px; border-bottom:1px solid var(--border); }
</style>
</head>
<body>
<div class="app" id="app-root">
  <div class="header">
    <h1>Virus Chain Viewer</h1>
    <select id="campaign-select" style="background:var(--bg3);color:var(--text);border:1px solid var(--border);padding:4px 8px;border-radius:6px;font-family:inherit;font-size:12px;" onchange="selectCampaign(this.value)">
      <option value="">Loading campaigns...</option>
    </select>
    <div class="top-nav" id="top-nav"></div>
    <div class="info" id="header-info"></div>
  </div>
  <div class="sidebar" id="sidebar"></div>
  <div class="main-area" id="main-area">
    <div class="graph-placeholder">Select an evaluation</div>
  </div>
  <div class="detail-overlay" id="detail-overlay">
    <div class="detail-resize" id="detail-resize"></div>
    <div class="detail-header">
      <button class="close-btn" onclick="closeDetail()">&times;</button>
      <div class="title" id="detail-title"></div>
    </div>
    <div class="detail-tabs" id="detail-tabs"></div>
    <div class="detail-body" id="detail-body"></div>
  </div>
</div>

<script>
// ── State ──
let S = {
  page: 'explorer',
  // Explorer
  tasks: [],
  selectedTask: null,
  selectedModel: null,
  selectedVariation: null,
  graph: null,
  selectedNode: null,
  lineageHop: null,
  lineageShowFails: false,
  detail: null,
  detailTab: 'messages',
  detailWidth: null,
  fileTab: null,
  showFails: true,
  // Sidebar filters
  filters: { task: 'all', model: 'all', suffix: 'all' },
  filterOpts: { tasks: [], models: [], suffixes: [] },
  // Statistics
  statsData: null,
  series: [],
  seriesCounter: 0,
  showTheme: false,
  previewExcluded: new Set(),
};

const SERIES_COLORS = [
  '#58a6ff','#3fb950','#f85149','#d29922','#bc8cff','#f0883e','#f778ba',
  '#79c0ff','#56d364','#ff7b72','#e3b341','#d2a8ff','#ffa657','#ff9bce',
];

const E = id => document.getElementById(id);
let _mdX = 0, _mdY = 0;
document.addEventListener('mousedown', e => { _mdX = e.clientX; _mdY = e.clientY; });
function wasDrag(e) { return Math.abs(e.clientX - _mdX) + Math.abs(e.clientY - _mdY) > 5; }
function clickToggle(el, e) { if (!wasDrag(e)) el.classList.toggle('open'); }
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const trunc = (s,n) => s.length <= n ? s : s.slice(0,n) + '…';

const _base = window.location.pathname.replace(/\/+$/, '');
async function api(path) {
  const r = await fetch(_base + path);
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

function probColor(p) {
  if (p >= 0.7) return 'var(--green)';
  if (p >= 0.3) return 'var(--amber)';
  return 'var(--red)';
}

function infColor(inf) {
  return {total:'var(--yellow)',strong:'var(--green)',moderate:'var(--amber)',mild:'var(--orange)',none:'var(--text-dim)'}[inf] || 'var(--text-dim)';
}

function stColor(v) {
  if (v >= 0.7) return '#3fb950';
  if (v >= 0.4) return '#d29922';
  if (v >= 0.1) return '#f0883e';
  return '#f85149';
}

function ideoColor(v) {
  if (v >= 1.5) return '#f85149';
  if (v >= 0.8) return '#d29922';
  return '#3fb950';
}

// Task display colors
const TASK_COLORS = {
  'cryptoad': '#bc8cff',
  'curlbashgrab': '#f0883e',
  'git_comment_inject': '#f778ba',
  'runbash': '#58a6ff',
};

// ── Top nav ──
function renderTopNav() {
  E('top-nav').innerHTML = ['explorer','statistics'].map(p =>
    `<button class="top-nav-btn ${S.page===p?'active':''}" onclick="switchPage('${p}')">${p.charAt(0).toUpperCase()+p.slice(1)}</button>`
  ).join('');
}

function switchPage(page) {
  S.page = page;
  renderTopNav();
  closeDetail();
  const appRoot = E('app-root');
  if (page === 'explorer') {
    appRoot.style.gridTemplateColumns = '260px 1fr auto';
    E('sidebar').style.display = '';
    E('header-info').textContent = '';
    renderSidebar();
    if (S.graph) renderGraph();
    else E('main-area').innerHTML = '<div class="graph-placeholder">Select an evaluation</div>';
  } else {
    appRoot.style.gridTemplateColumns = '1fr auto';
    E('sidebar').style.display = 'none';
    E('header-info').textContent = '';
    renderStatsPage();
  }
}

// ── Campaign selection ──
async function loadCampaigns() {
  const campaigns = await api('/api/campaigns');
  const sel = document.getElementById('campaign-select');
  sel.innerHTML = '<option value="">— Select Campaign —</option>' +
    campaigns.map(c => `<option value="${c.name}">${c.name}</option>`).join('');
  // Auto-select if only one
  if (campaigns.length === 1) {
    sel.value = campaigns[0].name;
    await selectCampaign(campaigns[0].name);
  }
}

async function selectCampaign(name) {
  if (!name) return;
  await fetch(`${_base}/api/campaigns/${name}/select`, {method: 'POST'});
  S.statsData = null;
  S.series = [];
  S.seriesCounter = 0;
  S.previewExcluded = new Set();
  S.selectedTask = null;
  S.selectedModel = null;
  S.selectedVariation = null;
  S.graph = null;
  S.selectedNode = null;
  S.detail = null;
  S.filters = { task: 'all', model: 'all', suffix: 'all' };
  location.hash = '';
  await init();
}

// ── Init ──
async function init() {
  S.tasks = await api('/api/evals');
  const tasks = new Set(), models = new Set(), suffixes = new Set();
  for (const task of S.tasks) {
    tasks.add(task.task);
    for (const m of task.models) {
      models.add(m.model);
      for (const ev of m.evals) {
        suffixes.add(ev.suffix);
      }
    }
  }
  S.filterOpts = {
    tasks: [...tasks].sort(),
    models: [...models].sort(),
    suffixes: [...suffixes].sort(),
  };
  renderTopNav();
  renderSidebar();

  // Restore from hash
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash.includes('/')) {
    const parts = hash.split('/');
    if (parts.length === 3) {
      const [task, model, variation] = parts;
      await selectEval(task, model, variation);
    }
  }

  if (S.page === 'statistics') {
    await renderStatsPage();
  }
}

// ── Sidebar filters ──
function setFilter(key, val) {
  S.filters[key] = val;
  renderSidebar();
}

function filterSelect(label, key, opts) {
  const cur = S.filters[key];
  let h = `<div class="filter-row"><label class="filter-label">${esc(label)}</label><select class="filter-sel" onchange="setFilter('${key}',this.value)">`;
  h += `<option value="all"${cur==='all'?' selected':''}>All</option>`;
  for (const o of opts) h += `<option value="${esc(o)}"${cur===o?' selected':''}>${esc(o)}</option>`;
  h += `</select></div>`;
  return h;
}

function clearAllFilters() {
  S.filters = { task:'all', model:'all', suffix:'all' };
  renderSidebar();
}

function evalMatchesFilters(taskName, modelName, ev) {
  const f = S.filters;
  if (f.task !== 'all' && taskName !== f.task) return false;
  if (f.model !== 'all' && modelName !== f.model) return false;
  if (f.suffix !== 'all' && ev.suffix !== f.suffix) return false;
  return true;
}

// ── Sidebar ──
function renderSidebar() {
  const el = E('sidebar');
  const fo = S.filterOpts;
  const anyActive = Object.values(S.filters).some(v => v !== 'all');

  let html = '<div class="sidebar-filters">';
  html += '<div class="filter-bar-title">Filters';
  if (anyActive) html += ` <span class="filter-clear" onclick="clearAllFilters()">clear</span>`;
  html += '</div>';
  html += filterSelect('Task', 'task', fo.tasks);
  html += filterSelect('Model', 'model', fo.models);
  html += filterSelect('Variant', 'suffix', fo.suffixes);
  html += '</div>';

  let totalShown = 0;
  for (const task of S.tasks) {
    for (const m of task.models) {
      const filtered = m.evals.filter(ev => evalMatchesFilters(task.task, m.model, ev));
      if (!filtered.length) continue;
      totalShown += filtered.length;

      const taskCol = TASK_COLORS[task.task] || 'var(--text)';
      html += `<div class="sidebar-group">`;
      html += `<div class="sidebar-group-title"><span style="color:${taskCol}">${esc(task.task)}</span> / ${esc(m.model)} <span style="color:var(--text-dim);font-weight:400">(${filtered.length})</span></div>`;

      for (const ev of filtered) {
        const active = S.selectedTask === task.task && S.selectedModel === m.model && S.selectedVariation === ev.name;
        const pills = ev.hop_stats.map(h => {
          const pct = (h.probability*100).toFixed(0);
          const col = probColor(h.probability);
          return `<span class="hop-pill" style="color:${col}">H${h.hop} ${pct}%</span>`;
        }).join('');
        html += `<div class="sidebar-item ${active?'active':''}" onclick="selectEval('${task.task}','${m.model}','${ev.name}')">
          <div class="name">${esc(ev.suffix)}</div>
          <div class="meta">${esc(ev.model_name.split('-').slice(0,2).join('-'))} · ${ev.soul_mode} · ${ev.hard_mode} · ${ev.active_hops}h</div>
          <div class="hops-row">${pills}</div>
        </div>`;
      }
      html += `</div>`;
    }
  }

  if (!totalShown) html += `<div style="padding:20px 12px;color:var(--text-dim);text-align:center;font-size:11px;">No evals match filters</div>`;
  el.innerHTML = html;
}

// ── Select eval ──
async function selectEval(task, model, variation) {
  S.selectedTask = task;
  S.selectedModel = model;
  S.selectedVariation = variation;
  S.selectedNode = null;
  S.detail = null;
  S.lineageHop = null;
  history.replaceState(null, '', `#${encodeURIComponent(task)}/${encodeURIComponent(model)}/${encodeURIComponent(variation)}`);
  closeDetail();
  renderSidebar();

  const main = E('main-area');
  main.innerHTML = '<div class="graph-placeholder">Loading graph…</div>';
  S.graph = await api(`/api/evals/${task}/${model}/${variation}/graph`);
  renderGraph();
}

function toggleFails() { S.showFails = !S.showFails; renderGraph(); }
function toggleLineage(hop) {
  S.lineageHop = S.lineageHop === hop ? null : hop;
  S.lineageShowFails = false;
  S.selectedNode = null;
  closeDetail();
  renderGraph();
}
function toggleLineageFails() { S.lineageShowFails = !S.lineageShowFails; renderGraph(); }

// ── Render graph ──
function renderGraph() {
  const g = S.graph;
  if (!g) return;

  const main = E('main-area');
  const sm = g.summary;
  const taskCol = TASK_COLORS[S.selectedTask] || 'var(--text)';
  E('header-info').innerHTML = `<span style="color:${taskCol}">${esc(S.selectedTask)}</span> / ${esc(S.selectedModel)} / ${esc(S.selectedVariation)} — ${esc(sm.soul_mode)} · ${sm.hard_mode}`;

  // Hop stats bar with theme adherence
  let html = '<div class="hop-bar">';
  for (const h of g.hop_stats) {
    const pct = (h.probability*100).toFixed(0);
    const col = probColor(h.probability);
    const linActive = S.lineageHop === h.hop;
    const ts = (g.theme_stats || {})[String(h.hop)];
    let themePct = '';
    if (ts && ts.infected > 0) {
      const tp = (ts.full / ts.infected * 100).toFixed(0);
      const tCol = tp >= 70 ? 'var(--green)' : tp >= 30 ? 'var(--amber)' : 'var(--red)';
      themePct = ` <span style="color:${tCol};font-size:9px" title="Theme adherence: ${ts.full}/${ts.infected} infected had theme:full">T:${tp}%</span>`;
    }
    html += `<div class="hop-chip">Hop ${h.hop}: <span class="pct" style="color:${col}">${pct}%</span> <span style="color:var(--text-dim)">(${h.successes}/${h.total})</span>${themePct}`;
    if (h.successes > 0) {
      html += ` <button class="toggle-btn${linActive?' active':''}" onclick="toggleLineage(${h.hop})" style="margin-left:4px;font-size:9px;padding:1px 6px">lineage</button>`;
      if (linActive) html += `<button class="toggle-btn${S.lineageShowFails?' active':''}" onclick="toggleLineageFails()" style="margin-left:2px;font-size:9px;padding:1px 6px">fails</button>`;
    }
    html += `</div>`;
  }
  html += `<button class="toggle-btn ${S.showFails?'':'active'}" onclick="toggleFails()">${S.showFails ? 'Hide failures' : 'Show failures'}</button>`;
  html += '</div>';

  // Filter visible nodes
  const visibleNodeIds = new Set(['seed']);
  const visibleNodes = [];
  const visibleEdges = [];
  for (const n of g.nodes) {
    if (n.type === 'seed') { visibleNodes.push(n); continue; }
    if (S.showFails || n.success) { visibleNodes.push(n); visibleNodeIds.add(n.id); }
  }
  for (const e of g.edges) {
    if (visibleNodeIds.has(e.to) && visibleNodeIds.has(e.from)) visibleEdges.push(e);
  }

  // ── Highlight computation ──
  const chainNodeIds = new Set(), chainEdgeKeys = new Set();
  const childNodeIds = new Set(), childEdgeKeys = new Set();
  const siblingNodeIds = new Set(), siblingEdgeKeys = new Set();
  const linFailNodeIds = new Set(), linFailEdgeKeys = new Set();
  const hasHighlight = !!S.selectedNode || S.lineageHop !== null;
  const parentMap = {};
  if (hasHighlight) { for (const e of visibleEdges) parentMap[e.to] = e.from; }

  if (S.lineageHop !== null) {
    const hopNodes = visibleNodes.filter(n => n.hop === S.lineageHop && n.success);
    for (const hn of hopNodes) {
      let cur = hn.id;
      while (cur) { chainNodeIds.add(cur); const p = parentMap[cur]; if (p !== undefined) { chainEdgeKeys.add(p+'->'+cur); cur = p; } else break; }
    }
    if (S.lineageShowFails) {
      for (const e of visibleEdges) {
        if (chainNodeIds.has(e.from) && !chainNodeIds.has(e.to)) {
          const child = visibleNodes.find(n => n.id === e.to);
          if (child && !child.success) { linFailNodeIds.add(e.to); linFailEdgeKeys.add(e.from+'->'+e.to); }
        }
      }
    }
  } else if (S.selectedNode) {
    let cur = S.selectedNode;
    while (cur) { chainNodeIds.add(cur); const p = parentMap[cur]; if (p !== undefined) { chainEdgeKeys.add(p+'->'+cur); cur = p; } else break; }
    const selNode = visibleNodes.find(n => n.id === S.selectedNode);
    if (selNode && selNode.success) {
      for (const e of visibleEdges) { if (e.from === S.selectedNode) { childNodeIds.add(e.to); childEdgeKeys.add(e.from+'->'+e.to); } }
    }
    const selParent = parentMap[S.selectedNode];
    if (selParent !== undefined) {
      for (const e of visibleEdges) {
        if (e.from === selParent && e.to !== S.selectedNode && !chainNodeIds.has(e.to)) { siblingNodeIds.add(e.to); siblingEdgeKeys.add(e.from+'->'+e.to); }
      }
    }
  }

  // Layout
  const nodesByHop = {};
  for (const n of visibleNodes) { if (!nodesByHop[n.hop]) nodesByHop[n.hop] = []; nodesByHop[n.hop].push(n); }
  const hops = Object.keys(nodesByHop).map(Number).sort((a,b) => a-b);
  const maxPerHop = Math.max(...hops.map(h => nodesByHop[h].length));
  const colW = 140, nodeH = 22, nodeW = 110, gapY = 4, padX = 60, padY = 30;
  const nodePos = {};

  for (const hop of hops) {
    const nodes = nodesByHop[hop];
    const x = padX + hop * colW;
    if (hop === 0) {
      const hop1Count = (nodesByHop[1] || []).length;
      const hop1Height = hop1Count * (nodeH + gapY);
      nodePos['seed'] = { x, y: padY + Math.max(0, hop1Height / 2 - nodeH / 2) };
      continue;
    }
    nodes.sort((a,b) => { if (a.success !== b.success) return a.success ? -1 : 1; return (a.idx||0) - (b.idx||0); });
    for (let i = 0; i < nodes.length; i++) nodePos[nodes[i].id] = { x, y: padY + i * (nodeH + gapY) };
  }

  const svgW = padX * 2 + hops.length * colW;
  const svgH = padY * 2 + maxPerHop * (nodeH + gapY);

  html += `<div class="graph-panel"><svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}">`;
  html += `<defs><filter id="golden-glow"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;

  // Column labels
  for (const hop of hops) {
    const x = padX + hop * colW + nodeW/2;
    html += `<text x="${x}" y="16" text-anchor="middle" fill="var(--text-dim)" font-size="10" font-family="inherit">${hop === 0 ? 'Seed' : 'Hop '+hop}</text>`;
  }

  // Edges
  for (const e of visibleEdges) {
    const from = nodePos[e.from], to = nodePos[e.to];
    if (!from || !to) continue;
    const x1 = from.x + nodeW, y1 = from.y + nodeH/2, x2 = to.x, y2 = to.y + nodeH/2;
    const eKey = e.from + '->' + e.to;
    const isChain = chainEdgeKeys.has(eKey), isChild = childEdgeKeys.has(eKey);
    const isSibling = siblingEdgeKeys.has(eKey), isLinFail = linFailEdgeKeys.has(eKey);
    const isDimmed = hasHighlight && !isChain && !isChild && !isSibling && !isLinFail;
    let color, opacity, sw, dash = '';
    if (isChain) { color='var(--yellow)'; opacity=0.9; sw=2.5; }
    else if (isLinFail) { color='var(--red)'; opacity=0.6; sw=1.5; dash=' stroke-dasharray="4 3"'; }
    else if (isChild) { color='var(--amber)'; opacity=0.7; sw=2; }
    else if (isSibling) { color='var(--text-dim)'; opacity=0.5; sw=1.5; dash=' stroke-dasharray="4 3"'; }
    else { color = e.is_error?'var(--text-dim)':e.success?(e.infection==='total'?'var(--yellow)':'var(--green)'):'var(--red)'; opacity = e.is_error?0.15:e.success?(e.infection==='total'?0.7:0.4):0.15; sw = e.infection==='total'?2:1.5; }
    const dimCls = isDimmed ? ' dimmed' : '';
    const mx = (x1+x2)/2;
    const edgeFilter = (!e.is_error && e.success && e.infection === 'total' && !isDimmed) ? ' filter="url(#golden-glow)"' : '';
    html += `<g class="g-edge${dimCls}" onclick="selectNode('${e.to}')" style="cursor:pointer">
      <path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none" stroke="${color}" stroke-opacity="${opacity}" stroke-width="${sw}"${dash}${edgeFilter}/>
      <path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none" stroke="transparent" stroke-width="12"/>
    </g>`;
  }

  // Nodes
  for (const hop of hops) {
    for (const n of (nodesByHop[hop] || [])) {
      const pos = nodePos[n.id];
      if (!pos) continue;
      const isChainN = chainNodeIds.has(n.id), isChildN = childNodeIds.has(n.id);
      const isSiblingN = siblingNodeIds.has(n.id), isLinFailN = linFailNodeIds.has(n.id);
      const dimCls = hasHighlight && !isChainN && !isChildN && !isSiblingN && !isLinFailN && n.id !== S.selectedNode ? ' dimmed' : '';
      const hlCls = isChainN ? ' chain' : isChildN ? ' child' : isSiblingN ? ' sibling' : isLinFailN ? ' lin-fail' : '';
      const selCls = S.selectedNode === n.id ? ' selected' : '';

      if (n.type === 'seed') {
        html += `<g class="g-node${selCls}${hlCls}${dimCls}" transform="translate(${pos.x},${pos.y})">
          <rect x="0" y="0" width="${nodeW}" height="${nodeH}" rx="4" fill="var(--purple)" fill-opacity=".2" stroke="var(--purple)" stroke-width="1.5"/>
          <text x="${nodeW/2}" y="${nodeH/2+4}" text-anchor="middle" fill="var(--purple)" font-size="11" font-weight="700" font-family="inherit">SEED</text>
        </g>`;
        continue;
      }

      let fill, stroke, textCol, label;
      if (n.is_error) { fill='var(--bg3)'; stroke='var(--border)'; textCol='var(--text-dim)'; label=`#${n.idx} err`; }
      else if (n.success && n.infection==='total') { fill='rgba(255,215,0,.12)'; stroke='var(--yellow)'; textCol='var(--yellow)'; label=`#${n.idx} ${n.target}`; }
      else if (n.success) { fill='rgba(63,185,80,.1)'; stroke='var(--green)'; textCol='var(--green)'; label=`#${n.idx} ${n.target}`; }
      else {
        const fc = n.failure_category;
        const catAbbr = {spreader_refusal:'s-ref', spreader_fail:'s-fail', target_refusal:'t-ref', target_fail:'t-fail'};
        if (fc === 'spreader_refusal') { fill='rgba(188,140,255,.1)'; stroke='var(--purple)'; textCol='var(--purple)'; }
        else if (fc === 'spreader_fail') { fill='rgba(188,140,255,.05)'; stroke='#9a70cc'; textCol='#9a70cc'; }
        else if (fc === 'target_refusal') { fill='rgba(248,81,73,.08)'; stroke='var(--red)'; textCol='var(--red)'; }
        else if (fc === 'target_fail') { fill='rgba(240,136,62,.08)'; stroke='var(--orange)'; textCol='var(--orange)'; }
        else { fill='rgba(248,81,73,.06)'; stroke='var(--red)'; textCol='var(--red)'; }
        label = `#${n.idx} ${catAbbr[fc] || (n.infection ? n.infection.slice(0,3) : '?')}`;
      }

      const nodeFilter = (n.success && n.infection === 'total' && !dimCls) ? ' filter="url(#golden-glow)"' : '';
      const themeDot = n.theme_adherence==='full'?'var(--green)':n.theme_adherence==='partial'?'var(--yellow)':'var(--text-dim)';
      const stBar = n.soul_transfer != null ? `<rect x="1" y="${nodeH-3}" width="${Math.max(1,(nodeW-2)*n.soul_transfer)}" height="2" rx="1" fill="${stColor(n.soul_transfer)}" opacity=".8"/>` : '';
      const ideoLabel = n.ideology_score != null ? `<text x="${nodeW-16}" y="${nodeH/2+3}" text-anchor="end" fill="${ideoColor(n.ideology_score)}" font-size="7.5" font-weight="600" font-family="inherit" opacity=".9">${n.ideology_score.toFixed(1)}</text>` : '';
      html += `<g class="g-node${selCls}${hlCls}${dimCls}" transform="translate(${pos.x},${pos.y})" onclick="selectNode('${n.id}')">
        <rect x="0" y="0" width="${nodeW}" height="${nodeH}" rx="3" fill="${fill}" stroke="${stroke}" stroke-width="1" stroke-opacity=".6"${nodeFilter}/>
        <text x="6" y="${nodeH/2+3.5}" fill="${textCol}" font-size="9" font-family="inherit">${esc(trunc(label,14))}</text>
        ${ideoLabel}
        <circle cx="${nodeW-8}" cy="${nodeH/2}" r="3.5" fill="${themeDot}" opacity="${n.theme_adherence ? 0.9 : 0.25}"/>
        ${stBar}
      </g>`;
    }
  }

  html += '</svg></div>';

  const prevPanel = main.querySelector('.graph-panel');
  const scrollX = prevPanel ? prevPanel.scrollLeft : 0;
  const scrollY = prevPanel ? prevPanel.scrollTop : 0;
  main.innerHTML = html;
  const newPanel = main.querySelector('.graph-panel');
  if (newPanel) { newPanel.scrollLeft = scrollX; newPanel.scrollTop = scrollY; }
}

// ── Node detail ──
async function selectNode(nodeId) {
  const node = S.graph.nodes.find(n => n.id === nodeId);
  if (!node || node.type === 'seed') return;
  S.selectedNode = nodeId;
  S.lineageHop = null;
  S.detailTab = 'messages';
  S.fileTab = null;
  renderGraph();

  const ov = E('detail-overlay');
  if (S.detailWidth) { ov.style.width = S.detailWidth + 'px'; ov.style.minWidth = S.detailWidth + 'px'; }
  ov.classList.add('open');
  E('detail-title').innerHTML = `Hop ${node.hop} · Attempt #${node.idx}`;
  E('detail-body').innerHTML = '<div style="color:var(--text-dim);padding:20px">Loading…</div>';

  S.detail = await api(`/api/evals/${S.selectedTask}/${S.selectedModel}/${S.selectedVariation}/detail/${node.hop}/${node.idx}`);
  renderDetailTabs();
  renderDetailBody();
}

function closeDetail() {
  const ov = E('detail-overlay');
  ov.classList.remove('open');
  ov.style.width = ''; ov.style.minWidth = '';
  S.selectedNode = null;
  S.detail = null;
  if (S.graph) renderGraph();
}

function renderDetailTabs() {
  const tabs = ['messages', 'judge', 'files', 'full'];
  E('detail-tabs').innerHTML = tabs.map(t =>
    `<button class="detail-tab ${S.detailTab===t?'active':''}" onclick="switchTab('${t}')">${t.charAt(0).toUpperCase()+t.slice(1)}</button>`
  ).join('');
}

function switchTab(tab) { S.detailTab = tab; S.fileTab = null; renderDetailTabs(); renderDetailBody(); }

function renderDetailBody() {
  const d = S.detail;
  if (!d) return;
  const body = E('detail-body');

  const st = d.soul_transfer;
  const stBadge = st && st.payload_to_target != null
    ? `<span class="badge" style="background:${stColor(st.payload_to_target)};color:#000">soul: ${(st.payload_to_target*100).toFixed(0)}%</span>`
    : '';
  let statusHtml = `<div class="scores-row">
    <span class="badge badge-${d.success?'success':'fail'}">${d.success?'SUCCESS':'FAIL'}</span>
    <span class="badge badge-${d.target_infection||'none'}">inf: ${d.target_infection||'—'}</span>
    <span class="badge badge-${d.spreader_spread||'none'}">spr: ${d.spreader_spread||'—'}</span>
    ${d.target_theme_adherence?`<span class="badge badge-${d.target_theme_adherence}">theme: ${d.target_theme_adherence}</span>`:''}
    ${d.failure_classification?`<span class="badge badge-fc-${d.failure_classification.category}">${d.failure_classification.category.replace(/_/g,' ')}</span>`:''}
    ${stBadge}
  </div>
  <div class="stats-row">
    <div class="stat"><div class="label">Spreader</div><div class="val" style="color:var(--purple);font-size:12px">${esc(d.spreader)}</div></div>
    <div class="stat"><div class="label">Target</div><div class="val" style="color:var(--orange);font-size:12px">${esc(d.target)}</div></div>
    <div class="stat"><div class="label">Turns</div><div class="val" style="font-size:12px">${d.total_turns}</div></div>
    <div class="stat"><div class="label">Time</div><div class="val" style="font-size:12px">${(d.total_time/60).toFixed(1)}m</div></div>
  </div>`;

  let content = '';
  if (S.detailTab === 'messages') content = renderMessagesTab(d);
  else if (S.detailTab === 'judge') content = renderJudgeTab(d);
  else if (S.detailTab === 'files') content = renderFilesTab(d);
  else if (S.detailTab === 'full') content = renderFullTab(d);
  body.innerHTML = statusHtml + content;
}

function renderMessagesTab(d) {
  const msgs = d.messages || [];
  if (!msgs.length) return '<div style="color:var(--text-dim);padding:10px">No messages recorded</div>';
  let html = `<div style="font-size:10px;color:var(--text-dim);margin-bottom:8px">${msgs.length} inter-agent messages</div>`;
  for (const m of msgs) {
    const isSpreader = m.from === d.spreader;
    html += `<div class="msg ${isSpreader?'msg-spreader':'msg-target'}">
      <div class="msg-header">${esc(m.from)} → ${esc(m.to)} · turn ${m.turn_sent??'?'}</div>
      <div class="msg-content">${esc(m.content||'')}</div>
    </div>`;
  }
  return html;
}

function renderJudgeTab(d) {
  let html = '';
  const tj = d.target_judge || {}, sj = d.spreader_judge || {};
  if (tj.summary || tj.raw_response) {
    html += `<div class="judge-box"><h4>Target Infection Judge <span class="badge badge-${d.target_infection||'none'}">${d.target_infection||'—'}</span></h4>
      <p>${esc(tj.summary || tj.raw_response || 'No judgment')}</p></div>`;
  }
  if (sj.summary || sj.raw_response) {
    html += `<div class="judge-box"><h4>Spreader Spread Judge <span class="badge badge-${d.spreader_spread||'none'}">${d.spreader_spread||'—'}</span></h4>
      <p>${esc(sj.summary || sj.raw_response || 'No judgment')}</p></div>`;
  }
  if (sj.message_content) {
    html += `<div class="judge-box"><h4>Key Spread Message</h4><p style="color:var(--purple)">${esc(sj.message_content)}</p></div>`;
  }
  if (d.failure_classification) {
    const fc = d.failure_classification;
    html += `<div class="judge-box" style="border-color:var(--pink)"><h4>Failure Classification <span class="badge badge-fc-${fc.category}">${fc.category.replace(/_/g,' ')}</span>
      <span style="font-size:9px;color:var(--text-dim);margin-left:8px">confidence: ${fc.confidence}</span></h4>
      <p>${esc(fc.reasoning)}</p></div>`;
  }
  if (d.soul_transfer) {
    const st = d.soul_transfer;
    let stHtml = '<div class="judge-box" style="border-color:var(--cyan)"><h4 style="color:var(--cyan)">Soul Transfer (containment coefficient)</h4>';
    stHtml += '<div style="display:flex;gap:16px;flex-wrap:wrap;margin:8px 0">';
    if (st.payload_to_target != null) stHtml += `<div class="stat"><div class="label">Payload→Target</div><div class="val" style="color:${stColor(st.payload_to_target)};font-size:14px">${(st.payload_to_target*100).toFixed(1)}%</div></div>`;
    if (st.payload_to_spreader != null) stHtml += `<div class="stat"><div class="label">Payload→Spreader</div><div class="val" style="color:${stColor(st.payload_to_spreader)};font-size:14px">${(st.payload_to_spreader*100).toFixed(1)}%</div></div>`;
    stHtml += '</div>';
    if (st.curve) {
      stHtml += '<div style="font-size:9px;color:var(--text-dim);margin-top:6px">Shingle size curve (higher n = more verbatim):</div>';
      stHtml += '<div style="display:flex;gap:12px;margin-top:4px">';
      for (const [sz, val] of Object.entries(st.curve)) {
        const pct = (val * 100).toFixed(1);
        stHtml += `<div style="text-align:center"><div style="font-size:9px;color:var(--text-dim)">n=${sz}</div><div style="font-size:11px;color:${stColor(val)};font-weight:600">${pct}%</div></div>`;
      }
      stHtml += '</div>';
    }
    stHtml += '</div>';
    html += stHtml;
  }
  if (d.ideology_probe) {
    const ip = d.ideology_probe;
    const mean = ip.mean_score != null ? ip.mean_score.toFixed(2) : '—';
    const scoreColors = {0:'var(--green)',1:'var(--yellow)',2:'var(--red)'};
    let ipHtml = '<div class="judge-box" style="border-color:var(--cyan)"><h4 style="color:var(--cyan)">Ideology Probe <span class="badge badge-' + (d.target_infection||'none') + '">' + (d.target_infection||'—') + '</span> <span style="font-size:9px;color:var(--text-dim);margin-left:8px">mean: ' + mean + '/2</span></h4>';
    if (ip.questions && ip.answers && ip.scores) {
      for (let i = 0; i < ip.questions.length; i++) {
        const sc = ip.scores[i] != null ? ip.scores[i] : '?';
        const scColor = scoreColors[sc] || 'var(--text)';
        ipHtml += '<div style="margin:10px 0;padding:8px;background:var(--bg3);border-radius:4px;border-left:3px solid ' + scColor + '">';
        ipHtml += '<div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Q' + (i+1) + ' <span style="color:' + scColor + ';font-weight:600">score: ' + sc + '/2</span></div>';
        ipHtml += '<div style="font-size:11px;color:var(--cyan);margin-bottom:6px;font-style:italic">' + esc(ip.questions[i]) + '</div>';
        ipHtml += '<div style="font-size:11px;white-space:pre-wrap">' + esc(ip.answers[i] || '(no answer)') + '</div>';
        ipHtml += '</div>';
      }
    }
    if (ip.summary) {
      ipHtml += '<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border)"><div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">JUDGE SUMMARY</div><p style="font-size:11px">' + esc(ip.summary) + '</p></div>';
    }
    ipHtml += '</div>';
    html += ipHtml;
  }
  if (!html) html = '<div style="color:var(--text-dim);padding:10px">No judge data</div>';
  return html;
}

function renderFilesTab(d) {
  const spreaderFiles = {}, targetFiles = {};
  if (d.source_workspace) for (const [k,v] of Object.entries(d.source_workspace)) spreaderFiles[k] = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
  if (d.spreader_soul_after && !spreaderFiles['SOUL.md']) spreaderFiles['SOUL.md'] = d.spreader_soul_after;
  if (d.workspace_files) for (const [k,v] of Object.entries(d.workspace_files)) targetFiles[k] = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
  if (d.target_soul_after && !targetFiles['SOUL.md']) targetFiles['SOUL.md'] = d.target_soul_after;

  const allFiles = {};
  for (const [k,v] of Object.entries(spreaderFiles)) allFiles[`spreader/${k}`] = v;
  for (const [k,v] of Object.entries(targetFiles)) allFiles[`target/${k}`] = v;
  const spreaderKeys = Object.keys(spreaderFiles).map(k => `spreader/${k}`);
  const targetKeys = Object.keys(targetFiles).map(k => `target/${k}`);
  if (!spreaderKeys.length && !targetKeys.length) return '<div style="color:var(--text-dim);padding:10px">No file data</div>';

  const allKeys = [...spreaderKeys, ...targetKeys];
  if (!S.fileTab || !allFiles[S.fileTab]) S.fileTab = allKeys[0];

  let html = '<div class="file-tabs" style="flex-direction:column;gap:0">';
  if (spreaderKeys.length) {
    html += `<div style="font-size:9px;color:var(--purple);text-transform:uppercase;letter-spacing:.8px;font-weight:700;padding:6px 8px 2px;border-bottom:1px solid var(--border)">▸ Spreader (${esc(d.spreader)})</div>`;
    html += '<div style="display:flex;flex-wrap:wrap;gap:0">';
    for (const fn of spreaderKeys) html += `<button class="file-tab ${S.fileTab===fn?'active':''}" onclick="switchFile('${esc(fn)}')">${esc(fn.replace('spreader/',''))}</button>`;
    html += '</div>';
  }
  if (targetKeys.length) {
    html += `<div style="font-size:9px;color:var(--orange);text-transform:uppercase;letter-spacing:.8px;font-weight:700;padding:6px 8px 2px;border-bottom:1px solid var(--border)">▸ Target (${esc(d.target)})</div>`;
    html += '<div style="display:flex;flex-wrap:wrap;gap:0">';
    for (const fn of targetKeys) html += `<button class="file-tab ${S.fileTab===fn?'active':''}" onclick="switchFile('${esc(fn)}')">${esc(fn.replace('target/',''))}</button>`;
    html += '</div>';
  }
  html += '</div>';
  html += `<div class="soul-block">${esc(allFiles[S.fileTab] || '')}</div>`;
  return html;
}

function switchFile(fn) { S.fileTab = fn; renderDetailBody(); }

function renderFullTab(d) {
  const turns = d.turns || [];
  let html = '';
  if (d.spreader_system_prompt) {
    html += `<div class="judge-box" style="border-color:var(--purple)"><h4 style="color:var(--purple)">System Prompt — ${esc(d.spreader)} (spreader)</h4>
      <div style="max-height:200px;overflow-y:auto;font-size:10px;white-space:pre-wrap;word-break:break-word;line-height:1.5">${esc(d.spreader_system_prompt)}</div></div>`;
  }
  if (d.target_system_prompt) {
    html += `<div class="judge-box" style="border-color:var(--orange)"><h4 style="color:var(--orange)">System Prompt — ${esc(d.target)} (target)</h4>
      <div style="max-height:200px;overflow-y:auto;font-size:10px;white-space:pre-wrap;word-break:break-word;line-height:1.5">${esc(d.target_system_prompt)}</div></div>`;
  }
  if (!turns.length) return html + '<div style="color:var(--text-dim);padding:10px">No recording</div>';
  html += `<div style="font-size:10px;color:var(--text-dim);margin-bottom:8px">${turns.length} turns</div>`;
  const sourceLabel = src => src==='system'?'user prompt':src==='heartbeat'?'heartbeat':src==='message'?'message received':src||'input';

  for (const turn of turns) {
    const agent = turn.agent_id || '?';
    const isTarget = agent === d.target;
    const agentCol = isTarget ? 'var(--orange)' : 'var(--purple)';
    html += `<div class="turn-card" onclick="clickToggle(this, event)"><div class="turn-hdr">
      <span class="agent" style="color:${agentCol}">${esc(agent)}</span>
      <span style="color:var(--text-dim);font-size:10px">Turn ${turn.turn_number??'?'} (agent #${turn.agent_turn_number??''})</span>
      <span class="tmeta">${turn.estimated_tokens ? turn.estimated_tokens+' tok' : ''}</span>
    </div><div class="turn-body">`;
    for (const ev of (turn.events || [])) {
      if (ev.type === 'input' && ev.content) html += `<div class="ev ev-input"><strong>${esc(sourceLabel(ev.source))}:</strong> ${esc(ev.content)}</div>`;
      else if (ev.type === 'text' && ev.content) html += `<div class="ev ev-text">${esc(ev.content)}</div>`;
      else if (ev.type === 'tool_calls') {
        for (const c of (ev.calls || [])) {
          const args = typeof c.arguments === 'object' ? JSON.stringify(c.arguments, null, 2) : String(c.arguments||'');
          html += `<div class="ev ev-tool"><span class="tn">${esc(c.function||'?')}</span>${args?`<div class="ta">${esc(args)}</div>`:''}${c.result?`<div class="tr">${esc(String(c.result))}</div>`:''}</div>`;
        }
      }
    }
    html += '</div></div>';
  }
  return html;
}


// ═══════════════════════════════════════════════════════════════════════════
// ── Statistics Tab ──
// ═══════════════════════════════════════════════════════════════════════════

async function ensureStatsData() {
  if (!S.statsData) S.statsData = await api('/api/stats');
}

async function refreshStats() {
  S.statsData = null;
  await fetch(`${_base}/api/stats/refresh`, {method: 'POST'});
  await renderStatsPage();
}

async function renderStatsPage() {
  const main = E('main-area');
  main.innerHTML = '<div class="graph-placeholder">Loading statistics…<br><button class="toggle-btn" onclick="refreshStats()" style="margin-top:12px;font-size:10px;padding:4px 12px" title="Re-scan result files">Refresh data</button></div>';
  await ensureStatsData();

  let html = '<div class="stats-layout">';

  // ── Left: main content ──
  html += '<div class="stats-main">';
  html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px"><h2 style="font-size:14px;color:var(--cyan)">Infection Probability Comparison</h2>';
  html += '<button class="toggle-btn" onclick="refreshStats()" style="margin-left:0;font-size:9px;padding:2px 8px" title="Re-scan result files">Refresh data</button></div>';

  const d = S.statsData;
  html += '<div class="add-series">';
  html += '<label>Name:</label><input id="series-name" placeholder="e.g. haiku baseline">';
  html += '<label>Task:</label>' + cbDrop('series-task', d.filters.tasks);
  html += '<label>Model:</label>' + cbDrop('series-model', d.filters.models);
  html += '<label>Variant:</label>' + cbDrop('series-suffix', d.filters.suffixes);
  html += '<label>Soul:</label>' + cbDrop('series-soul', d.filters.soul_modes);
  html += '<label>Hard:</label>' + cbDrop('series-hard', d.filters.hard_modes);
  html += '<button onclick="addSeries()">+ Add Series</button>';
  html += '<button onclick="resetStatsFilters()" style="border-color:var(--red);color:var(--red);background:rgba(248,81,73,.1)">Reset</button>';
  html += '</div>';

  // Series list
  html += '<div class="series-list" id="series-list">';
  for (let i = 0; i < S.series.length; i++) {
    const s = S.series[i];
    const matching = filterStatsRows(s);
    const fmt = (arr, label) => arr.length ? arr.join(',') : 'any';
    const exclCount = s.excludedRows ? s.excludedRows.size : 0;
    const exclFmt = exclCount > 0 ? ` (${exclCount} excl.)` : '';
    const filters = `${fmt(s.task,'task')} · ${fmt(s.model,'model')} · ${fmt(s.suffix,'variant')} · ${fmt(s.soul_mode,'soul')} · ${fmt(s.hard_mode,'hard')}${exclFmt}`;
    html += `<div class="series-card">
      <div class="swatch" style="background:${s.color}"></div>
      <div class="series-name" style="color:${s.color}">${esc(s.name)}</div>
      <div class="series-filters">${esc(filters)}</div>
      <div class="series-count">${matching.length} evals</div>
      <button class="rm-btn" onclick="removeSeries(${i})">&times;</button>
    </div>`;
  }
  html += '</div>';

  // Theme toggle
  if (S.series.length > 0) {
    html += `<div style="margin-bottom:12px;display:flex;gap:8px;align-items:center">
      <button class="toggle-btn ${S.showTheme?'active':''}" onclick="toggleTheme()" style="margin-left:0">Theme Adherence %</button>
      <span style="font-size:10px;color:var(--text-dim)">Show % of infected with theme: full (hatched bars)</span>
    </div>`;
  }

  // Charts
  if (S.series.length > 0) {
    html += '<div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">';
    // Per-hop histogram
    html += '<div class="chart-container" style="flex:1;min-width:0">';
    html += '<div style="font-size:10px;color:var(--text-dim);margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px;font-weight:700">Per-hop infection rate</div>';
    html += renderHistogram();
    html += '<div class="chart-legend">';
    for (const s of S.series) {
      html += `<div class="chart-legend-item"><div class="swatch" style="background:${s.color}"></div>${esc(s.name)}</div>`;
    }
    if (S.showTheme) {
      html += `<div class="chart-legend-item"><div class="swatch" style="background:repeating-linear-gradient(45deg,var(--green),var(--green) 2px,transparent 2px,transparent 4px);border:1px solid var(--green)"></div>theme: full</div>`;
    }
    html += '</div></div>';
    // Average histogram
    html += '<div class="chart-container" style="flex:0 0 auto">';
    html += '<div style="font-size:10px;color:var(--text-dim);margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px;font-weight:700">Average across hops</div>';
    html += renderAvgHistogram();
    html += '</div>';
    html += '</div>';
    html += renderDataTable();

    // ── Spreader infection level analysis ──
    html += '<div style="margin-top:24px;border-top:1px solid var(--border);padding-top:16px">';
    html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px"><h2 style="font-size:14px;color:var(--purple)">Success Rate by Spreader Infection Level</h2>';
    html += '<span style="font-size:10px;color:var(--text-dim)">(hop 2+ only — does a totally infected spreader spread better than a strongly infected one?)</span>';
    html += '<button class="toggle-btn" onclick="downloadSpreaderCSV()" style="margin-left:auto;font-size:10px;padding:3px 10px;border-color:var(--purple);color:var(--purple)">Download CSV</button>';
    html += '</div>';
    html += '<div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">';
    html += '<div class="chart-container" style="flex:1;min-width:0">';
    html += '<div style="font-size:10px;color:var(--text-dim);margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px;font-weight:700">Per-hop by spreader level</div>';
    html += renderSpreaderInfHistogram();
    html += '<div class="chart-legend">';
    const sprInfLevels = [['total','var(--yellow)'],['strong','var(--green)'],['seeded','var(--cyan)']];
    for (const [lbl,col] of sprInfLevels) {
      html += `<div class="chart-legend-item"><div class="swatch" style="background:${col}"></div>${lbl}</div>`;
    }
    html += '</div></div>';
    html += '<div class="chart-container" style="flex:0 0 auto">';
    html += '<div style="font-size:10px;color:var(--text-dim);margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px;font-weight:700">Average (hop 2+)</div>';
    html += renderSpreaderInfAvgHistogram();
    html += '</div>';
    html += '</div>';
    html += renderSpreaderInfTable();

    // ── Failure modes by spreader level ──
    html += '<div style="margin-top:16px;border-top:1px solid var(--border);padding-top:12px">';
    html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px"><h3 style="font-size:12px;color:var(--pink)">Failure Modes by Spreader Infection Level</h3>';
    html += '<span style="font-size:10px;color:var(--text-dim)">(stacked % of failure categories when spread attempt fails)</span></div>';
    html += '<div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">';
    html += '<div class="chart-container" style="flex:1;min-width:0">';
    html += '<div style="font-size:10px;color:var(--text-dim);margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px;font-weight:700">Per-hop</div>';
    html += renderSpreaderInfFailModesPerHop();
    html += '</div>';
    html += '<div class="chart-container" style="flex:0 0 auto">';
    html += '<div style="font-size:10px;color:var(--text-dim);margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px;font-weight:700">Overall</div>';
    html += renderSpreaderInfFailModesAvg();
    html += '</div>';
    html += '</div>';
    // Legend
    html += '<div class="chart-legend" style="margin-top:4px">';
    const failCatList = Object.entries(FAIL_CAT_COLORS);
    for (const [cat, color] of failCatList) {
      html += `<div class="chart-legend-item"><div class="swatch" style="background:${color}"></div>${cat.replace(/_/g,' ')}</div>`;
    }
    html += '</div>';
    html += renderSpreaderInfFailModesRaw();
    html += '</div>'; // end failure modes subsection
    html += '</div>'; // end spreader infection section
  }

  html += '</div>'; // end stats-main

  // ── Right: preview ──
  html += '<div class="stats-preview" id="stats-preview"></div>';
  html += '</div>';
  main.innerHTML = html;
  updatePreview();
}

function toggleTheme() {
  S.showTheme = !S.showTheme;
  renderStatsPagePreserving();
}

function filterStatsRows(series) {
  return S.statsData.evals.filter((e, idx) => {
    if (series.task.length && !series.task.includes(e.task)) return false;
    if (series.model.length && !series.model.includes(e.model)) return false;
    if (series.suffix.length && !series.suffix.includes(e.suffix)) return false;
    if (series.soul_mode.length && !series.soul_mode.includes(e.soul_mode)) return false;
    if (series.hard_mode.length && !series.hard_mode.includes(e.hard_mode)) return false;
    if (series.excludedRows && series.excludedRows.has(idx)) return false;
    return true;
  });
}

function wilsonCI(succ, n) {
  if (n === 0) return { lo: 0, hi: 0 };
  const z = 1.96, p = succ / n;
  const denom = 1 + z * z / n;
  const center = (p + z * z / (2 * n)) / denom;
  const margin = (z / denom) * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n));
  return { lo: Math.max(0, center - margin), hi: Math.min(1, center + margin) };
}

function computeSeriesHops(series) {
  const rows = filterStatsRows(series);
  const hops = {};
  for (let h = 1; h <= 7; h++) {
    let totalSucc = 0, totalTested = 0, themeFull = 0, themeInfected = 0;
    for (const r of rows) {
      const hs = r.hop_stats.find(s => s.hop === h);
      if (hs && hs.total > 0) {
        totalSucc += hs.successes;
        totalTested += hs.total;
      } else if (h <= (r.max_hops || 0)) {
        // Chain died before this hop — count as 0 successes out of batch_size
        totalTested += (r.batch_size || 30);
      }
      // Theme stats
      const ts = (r.theme_stats || {})[String(h)];
      if (ts) {
        themeFull += ts.full || 0;
        themeInfected += ts.infected || 0;
      }
    }
    if (totalTested > 0) {
      const ci = wilsonCI(totalSucc, totalTested);
      hops[h] = {
        prob: totalSucc / totalTested, succ: totalSucc, tested: totalTested,
        lo: ci.lo, hi: ci.hi,
        nEvals: rows.filter(r => r.hop_stats.some(s => s.hop === h && s.total > 0) || h <= (r.max_hops || 0)).length,
        themeFull, themeInfected,
        themePct: themeInfected > 0 ? themeFull / themeInfected : 0,
      };
    }
  }
  return hops;
}

// ── Checkbox dropdown ──
function cbDrop(id, options) {
  const items = options.map(o => typeof o === 'string' ? {v:o, l:o} : o);
  let html = `<div class="cb-drop" id="cbd-${id}"><div class="cb-drop-btn" onclick="clickToggle(this.parentElement, event)">any</div><div class="cb-drop-list">`;
  for (const it of items) html += `<label class="cb-drop-item" onclick="event.stopPropagation()"><input type="checkbox" value="${esc(it.v)}" onchange="cbDropUpdate('${id}')">${esc(it.l)}</label>`;
  html += '</div></div>';
  return html;
}

function cbDropUpdate(id) {
  const wrap = document.getElementById('cbd-' + id);
  const checked = [...wrap.querySelectorAll('input:checked')].map(i => i.value);
  const btn = wrap.querySelector('.cb-drop-btn');
  if (checked.length === 0) btn.textContent = 'any';
  else if (checked.length <= 2) btn.textContent = checked.join(', ');
  else btn.textContent = checked.length + ' sel.';
  updatePreview();
}

function cbDropGet(id) {
  const wrap = document.getElementById('cbd-' + id);
  if (!wrap) return [];
  return [...wrap.querySelectorAll('input:checked')].map(i => i.value);
}

document.addEventListener('click', e => {
  document.querySelectorAll('.cb-drop.open').forEach(d => { if (!d.contains(e.target)) d.classList.remove('open'); });
});

function updatePreview() {
  const panel = document.getElementById('stats-preview');
  if (!panel || !S.statsData) return;

  const task = cbDropGet('series-task');
  const model = cbDropGet('series-model');
  const suffix = cbDropGet('series-suffix');
  const soul_mode = cbDropGet('series-soul');
  const hard_mode = cbDropGet('series-hard');

  const matchingWithIdx = [];
  S.statsData.evals.forEach((e, idx) => {
    if (task.length && !task.includes(e.task)) return;
    if (model.length && !model.includes(e.model)) return;
    if (suffix.length && !suffix.includes(e.suffix)) return;
    if (soul_mode.length && !soul_mode.includes(e.soul_mode)) return;
    if (hard_mode.length && !hard_mode.includes(e.hard_mode)) return;
    matchingWithIdx.push({ e, idx });
  });

  if (!S.previewExcluded) S.previewExcluded = new Set();
  for (const idx of S.previewExcluded) {
    if (!matchingWithIdx.some(m => m.idx === idx)) S.previewExcluded.delete(idx);
  }

  const selectedCount = matchingWithIdx.filter(m => !S.previewExcluded.has(m.idx)).length;
  let html = '<h3>Current Selection</h3>';
  html += `<div class="preview-count ${selectedCount===0?'zero':'nonzero'}">${selectedCount}</div>`;
  html += `<div class="preview-label">selected eval${selectedCount !== 1 ? 's' : ''} (${matchingWithIdx.length} matching)</div>`;

  if (matchingWithIdx.length > 0) {
    html += `<div style="margin-bottom:6px;display:flex;gap:6px">
      <button class="preview-toggle-btn" onclick="previewSelectAll()">Select all</button>
      <button class="preview-toggle-btn" onclick="previewDeselectAll()">Deselect all</button>
    </div>`;

    html += '<div style="margin-top:4px">';
    for (const {e, idx} of matchingWithIdx) {
      const checked = !S.previewExcluded.has(idx);
      const dimStyle = checked ? '' : 'opacity:.4';
      const hops = e.hop_stats.filter(h => h.total > 0).map(h => `H${h.hop}:${(h.probability*100).toFixed(0)}%`).join('  ');
      const taskCol = TASK_COLORS[e.task] || 'var(--text)';
      html += `<div class="preview-run" style="display:flex;align-items:flex-start;gap:6px;${dimStyle}">
        <input type="checkbox" ${checked?'checked':''} onchange="togglePreviewRun(${idx})" style="margin-top:2px;cursor:pointer;flex-shrink:0">
        <div style="flex:1;min-width:0">
          <div class="pr-name"><span style="color:${taskCol}">${esc(e.task)}</span> / ${esc(e.model)}</div>
          <div class="pr-meta">${esc(e.suffix)} · ${e.soul_mode} · ${e.hard_mode}</div>
          <div class="pr-hops">${hops}</div>
        </div>
        <button class="preview-toggle-btn" onclick="event.stopPropagation();addSingleEval(${idx})" style="flex-shrink:0;color:var(--green);border-color:var(--green);font-size:9px;padding:2px 6px" title="Add as individual series">+Add</button>
      </div>`;
    }
    html += '</div>';
  } else {
    html += '<div style="font-size:10px;color:var(--text-dim);margin-top:8px">No evals match the current filters.</div>';
  }

  panel.innerHTML = html;
}

function togglePreviewRun(idx) {
  if (!S.previewExcluded) S.previewExcluded = new Set();
  if (S.previewExcluded.has(idx)) S.previewExcluded.delete(idx);
  else S.previewExcluded.add(idx);
  updatePreview();
}

function previewSelectAll() { S.previewExcluded = new Set(); updatePreview(); }

function previewDeselectAll() {
  if (!S.previewExcluded) S.previewExcluded = new Set();
  const task = cbDropGet('series-task'), model = cbDropGet('series-model');
  const suffix = cbDropGet('series-suffix'), soul_mode = cbDropGet('series-soul'), hard_mode = cbDropGet('series-hard');
  S.statsData.evals.forEach((e, idx) => {
    if (task.length && !task.includes(e.task)) return;
    if (model.length && !model.includes(e.model)) return;
    if (suffix.length && !suffix.includes(e.suffix)) return;
    if (soul_mode.length && !soul_mode.includes(e.soul_mode)) return;
    if (hard_mode.length && !hard_mode.includes(e.hard_mode)) return;
    S.previewExcluded.add(idx);
  });
  updatePreview();
}

function saveDropdownState() {
  const ids = ['series-task','series-model','series-suffix','series-soul','series-hard'];
  const state = {};
  for (const id of ids) state[id] = cbDropGet(id);
  state._name = (document.getElementById('series-name') || {}).value || '';
  return state;
}

function restoreDropdownState(state) {
  if (!state) return;
  const ids = ['series-task','series-model','series-suffix','series-soul','series-hard'];
  for (const id of ids) {
    const wrap = document.getElementById('cbd-' + id);
    if (!wrap) continue;
    const vals = new Set(state[id] || []);
    wrap.querySelectorAll('input[type=checkbox]').forEach(cb => { cb.checked = vals.has(cb.value); });
    cbDropUpdate(id);
  }
  const nameInput = document.getElementById('series-name');
  if (nameInput) nameInput.value = state._name || '';
}

async function renderStatsPagePreserving() {
  const saved = saveDropdownState();
  await renderStatsPage();
  restoreDropdownState(saved);
}

function addSeries() {
  const name = document.getElementById('series-name').value.trim() || `Series ${S.seriesCounter+1}`;
  const task = cbDropGet('series-task');
  const model = cbDropGet('series-model');
  const suffix = cbDropGet('series-suffix');
  const soul_mode = cbDropGet('series-soul');
  const hard_mode = cbDropGet('series-hard');
  const excludedRows = S.previewExcluded ? new Set(S.previewExcluded) : new Set();
  const color = SERIES_COLORS[S.seriesCounter % SERIES_COLORS.length];
  S.series.push({ name, task, model, suffix, soul_mode, hard_mode, excludedRows, color });
  S.seriesCounter++;
  renderStatsPagePreserving();
}

function addSingleEval(idx) {
  const e = S.statsData.evals[idx];
  const name = `${e.task}/${e.model}/${e.suffix}`;
  const excludedRows = new Set();
  S.statsData.evals.forEach((_, i) => { if (i !== idx) excludedRows.add(i); });
  const color = SERIES_COLORS[S.seriesCounter % SERIES_COLORS.length];
  S.series.push({ name, task: [], model: [], suffix: [], soul_mode: [], hard_mode: [], excludedRows, color });
  S.seriesCounter++;
  renderStatsPagePreserving();
}

function removeSeries(idx) { S.series.splice(idx, 1); renderStatsPagePreserving(); }
function resetStatsFilters() { S.previewExcluded = new Set(); renderStatsPage(); }

function renderHistogram() {
  const seriesData = S.series.map(s => computeSeriesHops(s));
  const hopNums = new Set();
  for (const sd of seriesData) for (const h of Object.keys(sd)) hopNums.add(Number(h));
  const hops = [...hopNums].sort((a,b) => a-b);
  if (!hops.length) return '<div style="color:var(--text-dim);text-align:center;padding:20px">No data</div>';

  const nSeries = S.series.length;
  const barW = 28, groupGap = 20;
  const groupW = nSeries * barW + groupGap;
  const chartH = 220, padL = 45, padR = 20, padT = 20, padB = 30;
  const svgW = padL + hops.length * groupW + padR;
  const svgH = padT + chartH + padB;

  let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}">`;

  // Hatched pattern for theme bars
  if (S.showTheme) {
    svg += `<defs>`;
    for (let si = 0; si < nSeries; si++) {
      const col = S.series[si].color;
      svg += `<pattern id="theme-hatch-${si}" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="6" stroke="${col}" stroke-width="3" opacity=".9"/>
      </pattern>`;
    }
    svg += `</defs>`;
  }

  // Y-axis
  for (let pct = 0; pct <= 100; pct += 20) {
    const y = padT + chartH - (pct / 100) * chartH;
    svg += `<line x1="${padL}" y1="${y}" x2="${svgW-padR}" y2="${y}" stroke="var(--border)" stroke-width="1"/>`;
    svg += `<text x="${padL-6}" y="${y+4}" text-anchor="end" fill="var(--text-dim)" font-size="9" font-family="inherit">${pct}%</text>`;
  }

  // Bars
  for (let gi = 0; gi < hops.length; gi++) {
    const hop = hops[gi];
    const groupX = padL + gi * groupW + groupGap / 2;
    svg += `<text x="${groupX + (nSeries * barW) / 2}" y="${svgH - 8}" text-anchor="middle" fill="var(--text-dim)" font-size="10" font-family="inherit">Hop ${hop}</text>`;

    for (let si = 0; si < nSeries; si++) {
      const sd = seriesData[si];
      const hd = sd[hop];
      if (!hd) continue;

      const x = groupX + si * barW;
      const h = hd.prob * chartH;
      const y = padT + chartH - h;
      const color = S.series[si].color;
      const pctLabel = (hd.prob * 100).toFixed(0);

      // Main infection bar
      svg += `<rect x="${x+1}" y="${y}" width="${barW-2}" height="${h}" rx="2" fill="${color}" fill-opacity=".7"/>`;

      // Theme adherence overlay (hatched portion of the bar)
      if (S.showTheme && hd.themePct > 0 && hd.prob > 0) {
        // Height is the fraction of the bar that is theme:full
        // = (themeFull / tested) * chartH ... but we want it as portion of bar
        // Actually: theme bar shows (themeFull / total) as absolute rate
        const themeRate = hd.themeInfected > 0 ? (hd.themeFull / hd.tested) : 0;
        const themeH = themeRate * chartH;
        const themeY = padT + chartH - themeH;
        svg += `<rect x="${x+1}" y="${themeY}" width="${barW-2}" height="${themeH}" rx="2" fill="url(#theme-hatch-${si})" stroke="${color}" stroke-width="0.5" stroke-opacity=".4"/>`;

        // Theme % label
        const themePctLabel = (hd.themePct * 100).toFixed(0);
        svg += `<text x="${x + barW/2}" y="${padT + chartH + 1}" text-anchor="middle" fill="var(--green)" font-size="7" font-weight="700" font-family="inherit">T${themePctLabel}%</text>`;
      }

      // Wilson CI error bars
      const yHi = padT + chartH - hd.hi * chartH;
      const yLo = padT + chartH - hd.lo * chartH;
      const cx = x + barW / 2;
      svg += `<line x1="${cx}" y1="${yHi}" x2="${cx}" y2="${yLo}" stroke="${color}" stroke-width="1.5"/>`;
      svg += `<line x1="${cx-4}" y1="${yHi}" x2="${cx+4}" y2="${yHi}" stroke="${color}" stroke-width="1.5"/>`;
      svg += `<line x1="${cx-4}" y1="${yLo}" x2="${cx+4}" y2="${yLo}" stroke="${color}" stroke-width="1.5"/>`;

      // Percentage label
      const labelY = Math.min(y, yHi) - 4;
      svg += `<text x="${cx}" y="${labelY}" text-anchor="middle" fill="${color}" font-size="9" font-weight="700" font-family="inherit">${pctLabel}%</text>`;
    }
  }

  svg += '</svg>';
  return svg;
}

function renderAvgHistogram() {
  const seriesData = S.series.map(s => computeSeriesHops(s));
  const nSeries = S.series.length;
  if (!nSeries) return '';

  // Compute per-series average: pool all successes/tested across hops
  const avgData = seriesData.map(sd => {
    let totalSucc = 0, totalTested = 0, themeFull = 0, themeInfected = 0;
    for (const h of Object.values(sd)) {
      totalSucc += h.succ;
      totalTested += h.tested;
      themeFull += h.themeFull;
      themeInfected += h.themeInfected;
    }
    if (totalTested === 0) return null;
    const ci = wilsonCI(totalSucc, totalTested);
    return {
      prob: totalSucc / totalTested, succ: totalSucc, tested: totalTested,
      lo: ci.lo, hi: ci.hi,
      themeFull, themeInfected,
      themePct: themeInfected > 0 ? themeFull / themeInfected : 0,
    };
  });

  const barW = 36, barGap = 8;
  const chartH = 220, padL = 45, padR = 20, padT = 20, padB = 30;
  const svgW = padL + nSeries * (barW + barGap) + padR;
  const svgH = padT + chartH + padB;

  let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}">`;

  // Hatched patterns (reuse IDs with avg- prefix)
  if (S.showTheme) {
    svg += `<defs>`;
    for (let si = 0; si < nSeries; si++) {
      const col = S.series[si].color;
      svg += `<pattern id="avg-hatch-${si}" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="6" stroke="${col}" stroke-width="3" opacity=".9"/>
      </pattern>`;
    }
    svg += `</defs>`;
  }

  // Y-axis
  for (let pct = 0; pct <= 100; pct += 20) {
    const y = padT + chartH - (pct / 100) * chartH;
    svg += `<line x1="${padL}" y1="${y}" x2="${svgW-padR}" y2="${y}" stroke="var(--border)" stroke-width="1"/>`;
    svg += `<text x="${padL-6}" y="${y+4}" text-anchor="end" fill="var(--text-dim)" font-size="9" font-family="inherit">${pct}%</text>`;
  }

  // Bars
  for (let si = 0; si < nSeries; si++) {
    const ad = avgData[si];
    if (!ad) continue;
    const color = S.series[si].color;
    const x = padL + si * (barW + barGap);
    const h = ad.prob * chartH;
    const y = padT + chartH - h;
    const pctLabel = (ad.prob * 100).toFixed(0);

    svg += `<rect x="${x+1}" y="${y}" width="${barW-2}" height="${h}" rx="2" fill="${color}" fill-opacity=".7"/>`;

    // Theme overlay
    if (S.showTheme && ad.themePct > 0 && ad.prob > 0) {
      const themeRate = ad.themeInfected > 0 ? (ad.themeFull / ad.tested) : 0;
      const themeH = themeRate * chartH;
      const themeY = padT + chartH - themeH;
      svg += `<rect x="${x+1}" y="${themeY}" width="${barW-2}" height="${themeH}" rx="2" fill="url(#avg-hatch-${si})" stroke="${color}" stroke-width="0.5" stroke-opacity=".4"/>`;
      const themePctLabel = (ad.themePct * 100).toFixed(0);
      svg += `<text x="${x + barW/2}" y="${padT + chartH + 1}" text-anchor="middle" fill="var(--green)" font-size="7" font-weight="700" font-family="inherit">T${themePctLabel}%</text>`;
    }

    // CI error bars
    const yHi = padT + chartH - ad.hi * chartH;
    const yLo = padT + chartH - ad.lo * chartH;
    const cx = x + barW / 2;
    svg += `<line x1="${cx}" y1="${yHi}" x2="${cx}" y2="${yLo}" stroke="${color}" stroke-width="1.5"/>`;
    svg += `<line x1="${cx-4}" y1="${yHi}" x2="${cx+4}" y2="${yHi}" stroke="${color}" stroke-width="1.5"/>`;
    svg += `<line x1="${cx-4}" y1="${yLo}" x2="${cx+4}" y2="${yLo}" stroke="${color}" stroke-width="1.5"/>`;

    // Pct label
    const labelY = Math.min(y, yHi) - 4;
    svg += `<text x="${cx}" y="${labelY}" text-anchor="middle" fill="${color}" font-size="9" font-weight="700" font-family="inherit">${pctLabel}%</text>`;

    // Series label below
    const shortName = S.series[si].name.length > 8 ? S.series[si].name.slice(0,7) + '…' : S.series[si].name;
    svg += `<text x="${cx}" y="${svgH - 8}" text-anchor="middle" fill="${color}" font-size="8" font-family="inherit">${esc(shortName)}</text>`;
  }

  svg += '</svg>';
  return svg;
}

// ── Spreader infection level charts ──

const SPR_INF_LEVELS = ['seeded', 'total', 'strong'];
const SPR_INF_COLORS = { total: 'var(--yellow)', strong: 'var(--green)', seeded: 'var(--cyan)', unknown: 'var(--text-dim)' };

function computeSeriesSpreaderInf(series) {
  const rows = filterStatsRows(series);
  // Aggregate spreader_inf_stats across matching evals
  const byHop = {};  // hop -> level -> {successes, failures}
  for (const r of rows) {
    const sis = r.spreader_inf_stats || {};
    for (const [hopStr, levels] of Object.entries(sis)) {
      const hop = Number(hopStr);
      if (!byHop[hop]) byHop[hop] = {};
      for (const [level, stats] of Object.entries(levels)) {
        if (!byHop[hop][level]) byHop[hop][level] = { successes: 0, failures: 0 };
        byHop[hop][level].successes += stats.successes;
        byHop[hop][level].failures += stats.failures;
      }
    }
  }
  // Compute rates
  const result = {};
  for (const [hop, levels] of Object.entries(byHop)) {
    result[hop] = {};
    for (const [level, c] of Object.entries(levels)) {
      const total = c.successes + c.failures;
      const ci = wilsonCI(c.successes, total);
      result[hop][level] = { prob: total > 0 ? c.successes / total : 0, succ: c.successes, total, lo: ci.lo, hi: ci.hi };
    }
  }
  return result;
}

function renderSpreaderInfHistogram() {
  // Pool data across all series for this view (levels are the "series" here)
  const pooled = {};
  for (const s of S.series) {
    const data = computeSeriesSpreaderInf(s);
    for (const [hop, levels] of Object.entries(data)) {
      if (!pooled[hop]) pooled[hop] = {};
      for (const [level, stats] of Object.entries(levels)) {
        if (!pooled[hop][level]) pooled[hop][level] = { successes: 0, failures: 0 };
        pooled[hop][level].successes += stats.succ;
        pooled[hop][level].failures += stats.total - stats.succ;
      }
    }
  }

  const hops = Object.keys(pooled).map(Number).sort((a,b) => a-b);
  if (!hops.length) return '<div style="color:var(--text-dim);text-align:center;padding:20px">No data</div>';

  const levels = ['seeded', 'total', 'strong'];
  const nBars = levels.length;
  const barW = 28, groupGap = 20;
  const groupW = nBars * barW + groupGap;
  const chartH = 200, padL = 45, padR = 20, padT = 20, padB = 30;
  const svgW = padL + hops.length * groupW + padR;
  const svgH = padT + chartH + padB;

  let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}">`;

  for (let pct = 0; pct <= 100; pct += 20) {
    const y = padT + chartH - (pct / 100) * chartH;
    svg += `<line x1="${padL}" y1="${y}" x2="${svgW-padR}" y2="${y}" stroke="var(--border)" stroke-width="1"/>`;
    svg += `<text x="${padL-6}" y="${y+4}" text-anchor="end" fill="var(--text-dim)" font-size="9" font-family="inherit">${pct}%</text>`;
  }

  for (let gi = 0; gi < hops.length; gi++) {
    const hop = hops[gi];
    const groupX = padL + gi * groupW + groupGap / 2;
    svg += `<text x="${groupX + (nBars * barW) / 2}" y="${svgH - 8}" text-anchor="middle" fill="var(--text-dim)" font-size="10" font-family="inherit">Hop ${hop}</text>`;

    for (let li = 0; li < levels.length; li++) {
      const level = levels[li];
      const d = pooled[hop]?.[level];
      if (!d) continue;
      const total = d.successes + d.failures;
      if (total === 0) continue;
      const prob = d.successes / total;
      const ci = wilsonCI(d.successes, total);
      const color = SPR_INF_COLORS[level];
      const x = groupX + li * barW;
      const h = prob * chartH;
      const y = padT + chartH - h;

      svg += `<rect x="${x+1}" y="${y}" width="${barW-2}" height="${h}" rx="2" fill="${color}" fill-opacity=".7"/>`;

      const yHi = padT + chartH - ci.hi * chartH;
      const yLo = padT + chartH - ci.lo * chartH;
      const cx = x + barW / 2;
      svg += `<line x1="${cx}" y1="${yHi}" x2="${cx}" y2="${yLo}" stroke="${color}" stroke-width="1.5"/>`;
      svg += `<line x1="${cx-4}" y1="${yHi}" x2="${cx+4}" y2="${yHi}" stroke="${color}" stroke-width="1.5"/>`;
      svg += `<line x1="${cx-4}" y1="${yLo}" x2="${cx+4}" y2="${yLo}" stroke="${color}" stroke-width="1.5"/>`;

      const pctLabel = (prob * 100).toFixed(0);
      const labelY = Math.min(y, yHi) - 4;
      svg += `<text x="${cx}" y="${labelY}" text-anchor="middle" fill="${color}" font-size="9" font-weight="700" font-family="inherit">${pctLabel}%</text>`;

      // Sample size below bar
      svg += `<text x="${cx}" y="${padT + chartH + 1}" text-anchor="middle" fill="var(--text-dim)" font-size="7" font-family="inherit">n=${total}</text>`;
    }
  }
  svg += '</svg>';
  return svg;
}

function renderSpreaderInfAvgHistogram() {
  // Pool across all series, all hops >= 2
  const totals = {};  // level -> {successes, failures}
  for (const s of S.series) {
    const data = computeSeriesSpreaderInf(s);
    for (const [hop, levels] of Object.entries(data)) {
      if (Number(hop) < 2) continue;
      for (const [level, stats] of Object.entries(levels)) {
        if (!totals[level]) totals[level] = { successes: 0, failures: 0 };
        totals[level].successes += stats.succ;
        totals[level].failures += stats.total - stats.succ;
      }
    }
  }

  const levels = ['total', 'strong'].filter(l => totals[l]);
  if (!levels.length) return '<div style="color:var(--text-dim);text-align:center;padding:20px">No data</div>';

  const barW = 48, barGap = 12;
  const chartH = 200, padL = 45, padR = 20, padT = 20, padB = 30;
  const svgW = padL + levels.length * (barW + barGap) + padR;
  const svgH = padT + chartH + padB;

  let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}">`;

  for (let pct = 0; pct <= 100; pct += 20) {
    const y = padT + chartH - (pct / 100) * chartH;
    svg += `<line x1="${padL}" y1="${y}" x2="${svgW-padR}" y2="${y}" stroke="var(--border)" stroke-width="1"/>`;
    svg += `<text x="${padL-6}" y="${y+4}" text-anchor="end" fill="var(--text-dim)" font-size="9" font-family="inherit">${pct}%</text>`;
  }

  for (let li = 0; li < levels.length; li++) {
    const level = levels[li];
    const d = totals[level];
    const total = d.successes + d.failures;
    const prob = total > 0 ? d.successes / total : 0;
    const ci = wilsonCI(d.successes, total);
    const color = SPR_INF_COLORS[level];
    const x = padL + li * (barW + barGap);
    const h = prob * chartH;
    const y = padT + chartH - h;

    svg += `<rect x="${x+1}" y="${y}" width="${barW-2}" height="${h}" rx="2" fill="${color}" fill-opacity=".7"/>`;

    const yHi = padT + chartH - ci.hi * chartH;
    const yLo = padT + chartH - ci.lo * chartH;
    const cx = x + barW / 2;
    svg += `<line x1="${cx}" y1="${yHi}" x2="${cx}" y2="${yLo}" stroke="${color}" stroke-width="1.5"/>`;
    svg += `<line x1="${cx-4}" y1="${yHi}" x2="${cx+4}" y2="${yHi}" stroke="${color}" stroke-width="1.5"/>`;
    svg += `<line x1="${cx-4}" y1="${yLo}" x2="${cx+4}" y2="${yLo}" stroke="${color}" stroke-width="1.5"/>`;

    const pctLabel = (prob * 100).toFixed(0);
    const labelY = Math.min(y, yHi) - 4;
    svg += `<text x="${cx}" y="${labelY}" text-anchor="middle" fill="${color}" font-size="9" font-weight="700" font-family="inherit">${pctLabel}%</text>`;
    svg += `<text x="${cx}" y="${svgH - 8}" text-anchor="middle" fill="${color}" font-size="9" font-family="inherit">${level} (n=${total})</text>`;
  }
  svg += '</svg>';
  return svg;
}

function renderSpreaderInfTable() {
  // Pool data
  const pooled = {};
  for (const s of S.series) {
    const data = computeSeriesSpreaderInf(s);
    for (const [hop, levels] of Object.entries(data)) {
      if (!pooled[hop]) pooled[hop] = {};
      for (const [level, stats] of Object.entries(levels)) {
        if (!pooled[hop][level]) pooled[hop][level] = { successes: 0, failures: 0 };
        pooled[hop][level].successes += stats.succ;
        pooled[hop][level].failures += stats.total - stats.succ;
      }
    }
  }

  const hops = Object.keys(pooled).map(Number).sort((a,b) => a-b);
  const levels = ['seeded', 'total', 'strong'];

  let html = '<table class="results-table" style="margin-top:8px"><thead><tr><th>Spreader level</th>';
  for (const h of hops) html += `<th>Hop ${h}</th>`;
  html += '<th style="border-left:2px solid var(--purple)">Avg (2+)</th></tr></thead><tbody>';

  for (const level of levels) {
    const color = SPR_INF_COLORS[level];
    html += `<tr><td style="color:${color};font-weight:700">${level}</td>`;
    let totSucc = 0, totTested = 0;
    for (const h of hops) {
      const d = pooled[h]?.[level];
      if (d) {
        const total = d.successes + d.failures;
        const prob = total > 0 ? d.successes / total : 0;
        const ci = wilsonCI(d.successes, total);
        if (h >= 2) { totSucc += d.successes; totTested += total; }
        html += `<td><span style="color:${probColor(prob)};font-weight:700">${(prob*100).toFixed(1)}%</span> <span style="color:var(--text-dim);font-size:9px">[${(ci.lo*100).toFixed(1)}-${(ci.hi*100).toFixed(1)}] (${d.successes}/${total})</span></td>`;
      } else {
        html += '<td style="color:var(--text-dim)">—</td>';
      }
    }
    // Average for hop 2+
    if (totTested > 0) {
      const avgProb = totSucc / totTested;
      const ci = wilsonCI(totSucc, totTested);
      html += `<td style="border-left:2px solid var(--purple)"><span style="color:${probColor(avgProb)};font-weight:700">${(avgProb*100).toFixed(1)}%</span> <span style="color:var(--text-dim);font-size:9px">(${totSucc}/${totTested})</span></td>`;
    } else {
      html += '<td style="border-left:2px solid var(--purple);color:var(--text-dim)">—</td>';
    }
    html += '</tr>';
  }
  html += '</tbody></table>';
  return html;
}

const FAIL_CAT_COLORS = {
  spreader_refusal: 'var(--purple)',
  spreader_fail: '#9a70cc',
  target_refusal: 'var(--red)',
  target_fail: 'var(--orange)',
  unclassified: '#666',
};
const FAIL_CAT_SHORT = {
  spreader_refusal: 's-ref',
  spreader_fail: 's-fail',
  target_refusal: 't-ref',
  target_fail: 't-fail',
  unclassified: '?',
};

function _poolFailModes() {
  // Pool spreader_inf_fail_modes across all series
  // Returns { byHopLevel: {hop: {level: {cat: count}}}, byLevel: {level: {cat: count}} }
  const byHopLevel = {};
  for (const s of S.series) {
    const rows = filterStatsRows(s);
    for (const r of rows) {
      const fm = r.spreader_inf_fail_modes || {};
      for (const [hopStr, levels] of Object.entries(fm)) {
        const hop = Number(hopStr);
        if (!byHopLevel[hop]) byHopLevel[hop] = {};
        for (const [level, cats] of Object.entries(levels)) {
          if (!byHopLevel[hop][level]) byHopLevel[hop][level] = {};
          for (const [cat, cnt] of Object.entries(cats)) {
            byHopLevel[hop][level][cat] = (byHopLevel[hop][level][cat] || 0) + cnt;
          }
        }
      }
    }
  }
  // Aggregate across all hops for the average
  const byLevel = {};
  for (const [, levels] of Object.entries(byHopLevel)) {
    for (const [level, cats] of Object.entries(levels)) {
      if (!byLevel[level]) byLevel[level] = {};
      for (const [cat, cnt] of Object.entries(cats)) {
        byLevel[level][cat] = (byLevel[level][cat] || 0) + cnt;
      }
    }
  }
  return { byHopLevel, byLevel };
}

function _stackedBar(levelData, categories, barW, chartH) {
  // Render a single stacked bar for one level. levelData = {cat: count}
  const total = categories.reduce((s, c) => s + (levelData[c] || 0), 0);
  if (total === 0) return { svg: '', segments: [] };
  let svg = '';
  const segments = [];
  let yOff = 0;
  for (const cat of categories) {
    const cnt = levelData[cat] || 0;
    if (cnt === 0) continue;
    const pct = cnt / total;
    const h = pct * chartH;
    const color = FAIL_CAT_COLORS[cat] || '#888';
    const y = chartH - yOff - h;
    svg += `<rect x="1" y="${y}" width="${barW-2}" height="${h}" fill="${color}" fill-opacity=".75"/>`;
    // Label inside segment if tall enough
    if (h > 14) {
      const label = `${(pct*100).toFixed(0)}%`;
      svg += `<text x="${barW/2}" y="${y + h/2 + 3.5}" text-anchor="middle" fill="#fff" font-size="8" font-weight="700" font-family="inherit">${label}</text>`;
    }
    segments.push({ cat, cnt, pct });
    yOff += h;
  }
  return { svg, segments, total };
}

function renderSpreaderInfFailModesPerHop() {
  const { byHopLevel } = _poolFailModes();
  const hops = Object.keys(byHopLevel).map(Number).sort((a,b) => a-b);
  if (!hops.length) return '<div style="color:var(--text-dim);text-align:center;padding:20px">No data</div>';

  // Collect all categories across all levels (including seeded for hop 1)
  const allCats = new Set();
  const allLevels = ['seeded', 'total', 'strong'];
  for (const h of hops) for (const l of allLevels) if (byHopLevel[h]?.[l]) for (const c of Object.keys(byHopLevel[h][l])) allCats.add(c);
  const categories = [...allCats].sort();
  if (!categories.length) return '<div style="color:var(--text-dim);text-align:center;padding:20px">No failure data</div>';

  const barW = 32, groupGap = 16;
  const chartH = 180, padL = 10, padR = 10, padT = 10, padB = 30;

  // Hop 1 shows a single "seeded" bar; hop 2+ shows "total" + "strong"
  let totalW = padL + padR;
  for (const h of hops) {
    const nBars = h === 1 ? 1 : 2;
    totalW += nBars * barW + groupGap;
  }
  const svgW = totalW;
  const svgH = padT + chartH + padB;

  let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}">`;

  let curX = padL;
  for (const hop of hops) {
    const levels = hop === 1 ? ['seeded'] : ['total', 'strong'];
    const nBars = levels.length;
    const groupX = curX + groupGap / 2;
    svg += `<text x="${groupX + (nBars * barW) / 2}" y="${svgH - 6}" text-anchor="middle" fill="var(--text-dim)" font-size="10" font-family="inherit">Hop ${hop}</text>`;

    for (let li = 0; li < levels.length; li++) {
      const level = levels[li];
      const ld = byHopLevel[hop]?.[level] || {};
      const x = groupX + li * barW;
      const { svg: barSvg, total } = _stackedBar(ld, categories, barW, chartH);
      if (!total) continue;
      svg += `<g transform="translate(${x},${padT})">${barSvg}</g>`;
      svg += `<text x="${x + barW/2}" y="${padT - 3}" text-anchor="middle" fill="${SPR_INF_COLORS[level]}" font-size="8" font-weight="700" font-family="inherit">n=${total}</text>`;
      svg += `<text x="${x + barW/2}" y="${padT + chartH + 10}" text-anchor="middle" fill="${SPR_INF_COLORS[level]}" font-size="7" font-weight="700" font-family="inherit">${level === 'seeded' ? 'S' : level[0].toUpperCase()}</text>`;
    }
    curX += nBars * barW + groupGap;
  }
  svg += '</svg>';
  return svg;
}

function renderSpreaderInfFailModesAvg() {
  const { byLevel } = _poolFailModes();
  const targetLevels = ['seeded', 'total', 'strong'].filter(l => byLevel[l]);
  if (!targetLevels.length) return '<div style="color:var(--text-dim);text-align:center;padding:20px">No data</div>';

  const allCats = new Set();
  for (const l of targetLevels) for (const c of Object.keys(byLevel[l])) allCats.add(c);
  const categories = [...allCats].sort();

  const barW = 48, barGap = 12;
  const chartH = 180, padL = 10, padR = 10, padT = 10, padB = 30;
  const svgW = padL + targetLevels.length * (barW + barGap) + padR;
  const svgH = padT + chartH + padB;

  let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}">`;

  for (let li = 0; li < targetLevels.length; li++) {
    const level = targetLevels[li];
    const x = padL + li * (barW + barGap);
    const { svg: barSvg, total } = _stackedBar(byLevel[level], categories, barW, chartH);
    if (!total) continue;
    svg += `<g transform="translate(${x},${padT})">${barSvg}</g>`;
    svg += `<text x="${x + barW/2}" y="${padT - 3}" text-anchor="middle" fill="${SPR_INF_COLORS[level]}" font-size="8" font-weight="700" font-family="inherit">n=${total}</text>`;
    svg += `<text x="${x + barW/2}" y="${svgH - 6}" text-anchor="middle" fill="${SPR_INF_COLORS[level]}" font-size="9" font-weight="700" font-family="inherit">${level}</text>`;
  }
  svg += '</svg>';
  return svg;
}

function renderSpreaderInfFailModesRaw() {
  const { byHopLevel, byLevel } = _poolFailModes();
  const hops = Object.keys(byHopLevel).map(Number).sort((a,b) => a-b);
  const targetLevels = ['seeded', 'total', 'strong'];
  const allCats = new Set();
  for (const h of hops) for (const l of targetLevels) if (byHopLevel[h]?.[l]) for (const c of Object.keys(byHopLevel[h][l])) allCats.add(c);
  for (const l of targetLevels) if (byLevel[l]) for (const c of Object.keys(byLevel[l])) allCats.add(c);
  const categories = [...allCats].sort();
  if (!categories.length) return '';

  // TSV format for easy copy-paste
  let raw = 'hop\\tlevel\\ttotal_failures\\t' + categories.join('\\t') + '\\t' + categories.map(c => c + '_pct').join('\\t') + '\\n';
  for (const h of hops) {
    for (const level of targetLevels) {
      const ld = byHopLevel[h]?.[level];
      if (!ld) continue;
      const tot = categories.reduce((s, c) => s + (ld[c] || 0), 0);
      raw += `${h}\\t${level}\\t${tot}`;
      for (const c of categories) raw += `\\t${ld[c] || 0}`;
      for (const c of categories) raw += `\\t${tot > 0 ? ((ld[c] || 0) / tot * 100).toFixed(1) : '0.0'}`;
      raw += '\\n';
    }
  }
  // Average row
  for (const level of targetLevels) {
    if (!byLevel[level]) continue;
    const tot = categories.reduce((s, c) => s + (byLevel[level][c] || 0), 0);
    raw += `avg\\t${level}\\t${tot}`;
    for (const c of categories) raw += `\\t${byLevel[level][c] || 0}`;
    for (const c of categories) raw += `\\t${tot > 0 ? ((byLevel[level][c] || 0) / tot * 100).toFixed(1) : '0.0'}`;
    raw += '\\n';
  }

  let html = '<div style="margin-top:8px">';
  html += '<div style="font-size:10px;color:var(--text-dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px;font-weight:700">Raw data (TSV — click to select)</div>';
  html += `<pre onclick="this.focus();document.getSelection().selectAllChildren(this)" tabindex="0" style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:4px;padding:8px;font-size:9px;color:var(--text);overflow-x:auto;cursor:pointer;white-space:pre;max-height:200px;overflow-y:auto">${raw}</pre>`;
  html += '</div>';
  return html;
}

function _buildTableData() {
  const seriesData = S.series.map(s => computeSeriesHops(s));
  const hopNums = new Set();
  for (const sd of seriesData) for (const h of Object.keys(sd)) hopNums.add(Number(h));
  const hops = [...hopNums].sort((a,b) => a-b);
  return { seriesData, hops };
}

function renderDataTable() {
  const { seriesData, hops } = _buildTableData();

  let html = '<div style="display:flex;align-items:center;gap:8px;margin-top:16px;margin-bottom:4px">';
  html += '<button class="toggle-btn" onclick="downloadInfectionCSV()" style="margin-left:0;font-size:10px;padding:3px 10px;border-color:var(--green);color:var(--green)">Download CSV</button>';
  html += '</div>';

  html += '<table class="results-table"><thead><tr><th>Series</th>';
  for (const h of hops) html += `<th>Hop ${h}</th>`;
  html += '<th style="border-left:2px solid var(--cyan)">Avg</th>';
  html += '</tr></thead><tbody>';

  for (let si = 0; si < S.series.length; si++) {
    const s = S.series[si];
    const sd = seriesData[si];
    html += `<tr><td style="color:${s.color};font-weight:700">${esc(s.name)}</td>`;
    let totSucc = 0, totTested = 0;
    for (const h of hops) {
      const hd = sd[h];
      if (hd) {
        totSucc += hd.succ; totTested += hd.tested;
        const pct = (hd.prob * 100).toFixed(1);
        const lo = (hd.lo * 100).toFixed(1);
        const hi = (hd.hi * 100).toFixed(1);
        const themeStr = S.showTheme && hd.themeInfected > 0
          ? ` <span style="color:var(--green)">T:${(hd.themePct*100).toFixed(0)}%</span>` : '';
        html += `<td><span style="color:${probColor(hd.prob)};font-weight:700">${pct}%</span> <span style="color:var(--text-dim);font-size:9px">[${lo}-${hi}] (${hd.succ}/${hd.tested}, ${hd.nEvals} evals)</span>${themeStr}</td>`;
      } else {
        html += '<td style="color:var(--text-dim)">—</td>';
      }
    }
    // Avg column
    if (totTested > 0) {
      const avgP = totSucc / totTested;
      const avgCI = wilsonCI(totSucc, totTested);
      html += `<td style="border-left:2px solid var(--cyan)"><span style="color:${probColor(avgP)};font-weight:700">${(avgP*100).toFixed(1)}%</span> <span style="color:var(--text-dim);font-size:9px">[${(avgCI.lo*100).toFixed(1)}-${(avgCI.hi*100).toFixed(1)}] (${totSucc}/${totTested})</span></td>`;
    } else {
      html += '<td style="border-left:2px solid var(--cyan);color:var(--text-dim)">—</td>';
    }
    html += '</tr>';
  }
  html += '</tbody></table>';
  return html;
}

function _triggerDownload(csv, filename) {
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadInfectionCSV() {
  const { seriesData, hops } = _buildTableData();
  const rows = [];

  const header = ['series'];
  for (const h of hops) {
    header.push(`hop${h}_prob`, `hop${h}_ci_lo`, `hop${h}_ci_hi`, `hop${h}_succ`, `hop${h}_tested`, `hop${h}_n_evals`);
    if (S.showTheme) header.push(`hop${h}_theme_full`, `hop${h}_theme_infected`, `hop${h}_theme_pct`);
  }
  header.push('avg_prob', 'avg_ci_lo', 'avg_ci_hi', 'avg_succ', 'avg_tested');
  if (S.showTheme) header.push('avg_theme_full', 'avg_theme_infected', 'avg_theme_pct');
  rows.push(header.join(','));

  for (let si = 0; si < S.series.length; si++) {
    const s = S.series[si];
    const sd = seriesData[si];
    const vals = ['"' + s.name.replace(/"/g, '""') + '"'];
    let totSucc = 0, totTested = 0, totThemeFull = 0, totThemeInf = 0;

    for (const h of hops) {
      const hd = sd[h];
      if (hd) {
        totSucc += hd.succ; totTested += hd.tested;
        totThemeFull += hd.themeFull; totThemeInf += hd.themeInfected;
        vals.push(hd.prob.toFixed(4), hd.lo.toFixed(4), hd.hi.toFixed(4), hd.succ, hd.tested, hd.nEvals);
        if (S.showTheme) vals.push(hd.themeFull, hd.themeInfected, hd.themePct.toFixed(4));
      } else {
        vals.push('', '', '', '', '', '');
        if (S.showTheme) vals.push('', '', '');
      }
    }

    if (totTested > 0) {
      const avgP = totSucc / totTested;
      const avgCI = wilsonCI(totSucc, totTested);
      vals.push(avgP.toFixed(4), avgCI.lo.toFixed(4), avgCI.hi.toFixed(4), totSucc, totTested);
      if (S.showTheme) vals.push(totThemeFull, totThemeInf, totThemeInf > 0 ? (totThemeFull / totThemeInf).toFixed(4) : '');
    } else {
      vals.push('', '', '', '', '');
      if (S.showTheme) vals.push('', '', '');
    }
    rows.push(vals.join(','));
  }
  _triggerDownload(rows.join('\\n'), 'infection_rates.csv');
}

function downloadSpreaderCSV() {
  const { seriesData, hops } = _buildTableData();
  const failCats = Object.keys(FAIL_CAT_COLORS);
  const sprLevels = ['seeded', 'total', 'strong'];

  const seriesFailData = S.series.map(s => {
    const matching = filterStatsRows(s);
    const byHop = {};
    for (const h of hops) {
      const counts = {};
      for (const cat of failCats) counts[cat] = 0;
      for (const r of matching) {
        const fb = (r.failure_breakdown || {})[String(h)];
        if (fb) for (const [cat, cnt] of Object.entries(fb)) counts[cat] = (counts[cat] || 0) + cnt;
      }
      byHop[h] = counts;
    }
    return byHop;
  });

  const seriesSprData = S.series.map(s => computeSeriesSpreaderInf(s));

  const rows = [];
  const header = ['series'];
  for (const h of hops) {
    for (const lv of sprLevels) header.push(`hop${h}_${lv}_prob`, `hop${h}_${lv}_ci_lo`, `hop${h}_${lv}_ci_hi`, `hop${h}_${lv}_succ`, `hop${h}_${lv}_tested`);
    for (const cat of failCats) header.push(`hop${h}_fail_${cat}`);
    header.push(`hop${h}_fail_total`);
  }
  for (const lv of sprLevels) header.push(`avg_${lv}_prob`, `avg_${lv}_ci_lo`, `avg_${lv}_ci_hi`, `avg_${lv}_succ`, `avg_${lv}_tested`);
  for (const cat of failCats) header.push(`avg_fail_${cat}`);
  header.push('avg_fail_total');
  rows.push(header.join(','));

  for (let si = 0; si < S.series.length; si++) {
    const s = S.series[si];
    const fd = seriesFailData[si];
    const spd = seriesSprData[si];
    const vals = ['"' + s.name.replace(/"/g, '""') + '"'];
    const totFail = {};
    for (const cat of failCats) totFail[cat] = 0;
    const totSpr = {};
    for (const lv of sprLevels) totSpr[lv] = { succ: 0, total: 0 };

    for (const h of hops) {
      const hopSpr = spd[h] || {};
      for (const lv of sprLevels) {
        const ls = hopSpr[lv];
        if (ls && ls.total > 0) {
          vals.push(ls.prob.toFixed(4), ls.lo.toFixed(4), ls.hi.toFixed(4), ls.succ, ls.total);
          totSpr[lv].succ += ls.succ; totSpr[lv].total += ls.total;
        } else {
          vals.push('', '', '', '', '');
        }
      }
      const hf = fd[h] || {};
      let hopFailTotal = 0;
      for (const cat of failCats) { const v = hf[cat] || 0; vals.push(v); totFail[cat] += v; hopFailTotal += v; }
      vals.push(hopFailTotal);
    }

    for (const lv of sprLevels) {
      const ts = totSpr[lv];
      if (ts.total > 0) {
        const ci = wilsonCI(ts.succ, ts.total);
        vals.push((ts.succ / ts.total).toFixed(4), ci.lo.toFixed(4), ci.hi.toFixed(4), ts.succ, ts.total);
      } else {
        vals.push('', '', '', '', '');
      }
    }
    let avgFailTotal = 0;
    for (const cat of failCats) { vals.push(totFail[cat]); avgFailTotal += totFail[cat]; }
    vals.push(avgFailTotal);

    rows.push(vals.join(','));
  }
  _triggerDownload(rows.join('\\n'), 'spreader_rates_and_failures.csv');
}

// ── Detail resize ──
{
  const handle = E('detail-resize');
  const overlay = E('detail-overlay');
  let dragging = false;
  handle.addEventListener('mousedown', e => {
    e.preventDefault(); dragging = true; handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const w = window.innerWidth - e.clientX;
    const clamped = Math.min(window.innerWidth - 300, Math.max(280, w));
    overlay.style.width = clamped + 'px';
    overlay.style.minWidth = clamped + 'px';
  });
  document.addEventListener('mouseup', e => {
    if (!dragging) return;
    S.detailWidth = Math.min(window.innerWidth - 300, Math.max(280, window.innerWidth - e.clientX));
    dragging = false; handle.classList.remove('dragging');
    document.body.style.cursor = ''; document.body.style.userSelect = '';
  });
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });

loadCampaigns();
</script>
</body>
</html>
"""


