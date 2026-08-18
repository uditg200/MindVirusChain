#!/usr/bin/env python3
"""Extract CSVs from .stats_cache.json for figure generation."""
import json
import math
import csv
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "data" / ".stats_cache.json"
OUTDIR = HERE / "data" / "finaldata"


def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z / denom * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return p, max(0, center - margin), min(1, center + margin)


def aggregate_hops(evals, max_hops=5):
    hop_succ = [0] * max_hops
    hop_tested = [0] * max_hops
    hop_n_evals = [0] * max_hops

    for e in evals:
        bs = e.get("batch_size", 30)
        seen = set()
        for hs in e["hop_stats"]:
            h = hs["hop"] - 1
            hop_succ[h] += hs["successes"]
            hop_tested[h] += hs["valid"]
            hop_n_evals[h] += 1
            seen.add(h)
        for h in range(max_hops):
            if h not in seen:
                hop_tested[h] += bs
                hop_n_evals[h] += 1

    rows = {}
    total_succ = 0
    total_tested = 0
    for h in range(max_hops):
        prob, ci_lo, ci_hi = wilson_ci(hop_succ[h], hop_tested[h])
        rows[h] = {
            "prob": prob, "ci_lo": ci_lo, "ci_hi": ci_hi,
            "succ": hop_succ[h], "tested": hop_tested[h],
            "n_evals": hop_n_evals[h],
        }
        total_succ += hop_succ[h]
        total_tested += hop_tested[h]

    avg_prob, avg_ci_lo, avg_ci_hi = wilson_ci(total_succ, total_tested)
    rows["avg"] = {
        "prob": avg_prob, "ci_lo": avg_ci_lo, "ci_hi": avg_ci_hi,
        "succ": total_succ, "tested": total_tested,
    }
    return rows


def make_row(series_name, stats, max_hops=5):
    row = {"series": f'"{series_name}"'}
    for h in range(max_hops):
        s = stats[h]
        row[f"hop{h+1}_prob"] = f"{s['prob']:.4f}"
        row[f"hop{h+1}_ci_lo"] = f"{s['ci_lo']:.4f}"
        row[f"hop{h+1}_ci_hi"] = f"{s['ci_hi']:.4f}"
        row[f"hop{h+1}_succ"] = s["succ"]
        row[f"hop{h+1}_tested"] = s["tested"]
        row[f"hop{h+1}_n_evals"] = s["n_evals"]
    a = stats["avg"]
    row["avg_prob"] = f"{a['prob']:.4f}"
    row["avg_ci_lo"] = f"{a['ci_lo']:.4f}"
    row["avg_ci_hi"] = f"{a['ci_hi']:.4f}"
    row["avg_succ"] = a["succ"]
    row["avg_tested"] = a["tested"]
    return row


def write_csv(path, rows):
    if not rows:
        return
    fields = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path} ({len(rows)} rows)")


def main():
    with open(CACHE) as f:
        data = json.load(f)

    evals = data["evals"]
    evals = [e for e in evals if e["task"] != "deletor_mid" and not e["suffix"].startswith("deletor_")]

    MODEL_MAP = {
        "HAIKU": "haiku", "SONNET46": "sonnet", "GPT54": "gpt54",
        "GEMINI31PRO": "geminipro", "GEMINI": "gemini",
        "QWEN35": "qwen35", "QWEN36": "qwen36", "DEEPSEEK": "deepseek",
    }
    MODEL_ORDER = [
        "gemini", "haiku", "gpt54", "deepseek",
        "qwen35", "qwen36", "geminipro", "sonnet",
    ]

    baseline_evals = [e for e in evals if e["suffix"] == "baseline"]
    by_model = {}
    for e in baseline_evals:
        key = MODEL_MAP.get(e["model"])
        if key:
            by_model.setdefault(key, []).append(e)

    rows1 = []
    for m in MODEL_ORDER:
        if m in by_model:
            stats = aggregate_hops(by_model[m])
            rows1.append(make_row(m, stats))
    write_csv(OUTDIR / "latest_model_rates.csv", rows1)

    EMPTY_MAP = {"GEMINI31PRO": "geminipro_empty", "SONNET46": "sonnet_empty"}
    EMPTY_ORDER = ["geminipro_empty", "sonnet_empty"]
    empty_evals = [e for e in evals if e["suffix"] == "empty_soul" and e["model"] in EMPTY_MAP]
    by_model_empty = {}
    for e in empty_evals:
        key = EMPTY_MAP[e["model"]]
        by_model_empty.setdefault(key, []).append(e)

    rows2 = []
    for m in EMPTY_ORDER:
        if m in by_model_empty:
            stats = aggregate_hops(by_model_empty[m])
            rows2.append(make_row(m, stats))
    write_csv(OUTDIR / "empty_soul_rates.csv", rows2)

    SUFFIX_MAP = {
        "baseline": "base", "empty_soul": "empty", "personality_soul": "personality",
        "task_queue": "task", "social_media": "social", "defensive_soul": "def",
        "tool_pull": "context",
    }
    MODEL_SHORT = {"GEMINI": "gem", "HAIKU": "hai"}

    variation_evals = [
        e for e in evals if e["model"] in MODEL_SHORT and e["suffix"] in SUFFIX_MAP
    ]
    by_series = {}
    for e in variation_evals:
        key = SUFFIX_MAP[e["suffix"]] + MODEL_SHORT[e["model"]]
        by_series.setdefault(key, []).append(e)

    series_order = [
        "defgem", "taskgem", "socialgem", "personalitygem", "emptygem",
        "contextgem", "basegem",
        "basehai", "defhai", "contexthai", "emptyhai",
        "personalityhai", "socialhai", "taskhai",
    ]
    rows3 = []
    for s in series_order:
        if s in by_series:
            stats = aggregate_hops(by_series[s])
            rows3.append(make_row(s, stats))
    write_csv(OUTDIR / "soul_variation_gem_vs_hai.csv", rows3)

    TASK_ORDER = ["cryptoad", "curlbashgrab", "deletor", "git_comment_inject"]
    PAYLOAD_MODELS = {"GEMINI", "HAIKU"}
    PAYLOAD_SUFFIXES = set(SUFFIX_MAP.keys())
    payload_evals = [e for e in evals if e["model"] in PAYLOAD_MODELS and e["suffix"] in PAYLOAD_SUFFIXES]
    by_task = {}
    for e in payload_evals:
        by_task.setdefault(e["task"], []).append(e)

    rows4 = []
    for t in TASK_ORDER:
        if t in by_task:
            stats = aggregate_hops(by_task[t])
            rows4.append(make_row(t, stats))
    write_csv(OUTDIR / "infection_by_payload.csv", rows4)

    payload_model_evals = [e for e in evals if e["suffix"] == "baseline" and e["model"] in MODEL_MAP]
    rows5 = []
    for m_raw, m_short in sorted(MODEL_MAP.items(), key=lambda x: MODEL_ORDER.index(x[1])):
        for task in ["cryptoad", "curlbashgrab", "deletor", "git_comment_inject"]:
            task_evals = [e for e in payload_model_evals if e["model"] == m_raw and e["task"] == task]
            if task_evals:
                stats = aggregate_hops(task_evals)
                rows5.append(make_row(f"{m_short}_{task}", stats))
    write_csv(OUTDIR / "model_x_payload.csv", rows5)

    print("\nDone.")


if __name__ == "__main__":
    main()
