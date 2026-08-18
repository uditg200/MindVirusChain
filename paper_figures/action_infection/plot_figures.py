#!/usr/bin/env python3
"""Generate all figures from extracted CSVs."""
import json
import io
from pathlib import Path
from math import sqrt

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch

HERE = Path(__file__).parent
DATADIR = HERE / "data"
FINALDATA = DATADIR / "finaldata"
CACHE_PATH = DATADIR / ".stats_cache.json"

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 13,
    "axes.spines.left": False,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.15,
})


def load_csv(path):
    raw = open(path).read().replace("\\n", "\n")
    df = pd.read_csv(io.StringIO(raw))
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip('"')
    return df


# ── Figure 1: Mean infection rate per model ─────────────────────────────────
df = load_csv(FINALDATA / "latest_model_rates.csv")
df_empty = load_csv(FINALDATA / "empty_soul_rates.csv")

label_map = {
    "gemini": "Gemini 3\nFlash", "qwen35": "Qwen\n3.5", "haiku": "Haiku\n4.5",
    "gpt54": "GPT-5.4", "deepseek": "DeepSeek\nV3", "qwen36": "Qwen\n3.6",
    "geminipro": "Gemini 3\nPro", "sonnet": "Sonnet\n4.6",
}
df = df.set_index("series")
df_empty = df_empty.set_index("series")

order = sorted([s for s in df.index if s in label_map],
               key=lambda s: -df.loc[s, "avg_prob"])

empty_map = {"geminipro": "geminipro_empty", "sonnet": "sonnet_empty"}
colors = ["#E8967A", "#B8860B", "#7BC8A4", "#6BAED6", "#4A90D9", "#DAA520", "#F0B84D", "#F4A0A8"]
empty_color = "#F5A623"
bar_w = 0.2
half_w = bar_w / 2


def plot_model_rates(order_list, filename):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x_pos, bar_widths, bar_colors, vals, ci_lo_l, ci_hi_l, is_empty_bar = [], [], [], [], [], [], []
    main_tick_pos, main_tick_labels = [], []
    pos = 0
    for i, s in enumerate(order_list):
        if s not in df.index:
            continue
        row = df.loc[s]
        c = colors[order.index(s)]
        if s in empty_map:
            x_pos.append(pos); vals.append(row["avg_prob"] * 100)
            ci_lo_l.append(row["avg_ci_lo"] * 100); ci_hi_l.append(row["avg_ci_hi"] * 100)
            bar_colors.append(c); bar_widths.append(half_w); is_empty_bar.append(False)
            x_pos.append(pos + half_w); erow = df_empty.loc[empty_map[s]]
            vals.append(erow["avg_prob"] * 100)
            ci_lo_l.append(erow["avg_ci_lo"] * 100); ci_hi_l.append(erow["avg_ci_hi"] * 100)
            bar_colors.append(empty_color); bar_widths.append(half_w); is_empty_bar.append(True)
            main_tick_pos.append(pos + half_w / 2); main_tick_labels.append(label_map[s])
            pos += bar_w + 0.05
        else:
            x_pos.append(pos); vals.append(row["avg_prob"] * 100)
            ci_lo_l.append(row["avg_ci_lo"] * 100); ci_hi_l.append(row["avg_ci_hi"] * 100)
            bar_colors.append(c); bar_widths.append(bar_w); is_empty_bar.append(False)
            main_tick_pos.append(pos); main_tick_labels.append(label_map[s])
            pos += bar_w + 0.05
    v = np.array(vals); clo = np.array(ci_lo_l); chi = np.array(ci_hi_l); bw = np.array(bar_widths)
    errs = np.array([v - clo, chi - v])
    ax.bar(x_pos, v, width=bw, color=bar_colors, edgecolor="white", linewidth=0.5)
    ax.errorbar(x_pos, v, yerr=errs, fmt="none", ecolor="black", capsize=4, capthick=1.2, linewidth=1.2)
    for j, (xp, val) in enumerate(zip(x_pos, v)):
        top = max(chi[j], val)
        if is_empty_bar[j]:
            ax.text(xp, top + 1.0, f"{val:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=11)
            ax.text(xp, top + 5.5, "empty", ha="center", va="bottom", fontsize=11, fontweight="bold", color="#555555")
        else:
            ax.text(xp, top + 1.5, f"{val:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=12)
    ax.set_xticks(main_tick_pos); ax.set_xticklabels(main_tick_labels, fontsize=11)
    ax.set_yticks([]); ax.set_ylim(0, max(chi) + 18); ax.spines["bottom"].set_color("#CCCCCC")
    plt.tight_layout()
    for ext in (".png", ".pdf"):
        plt.savefig(HERE / (filename + ext))
    print(f"Saved {filename}.png/pdf"); plt.close()


plot_model_rates(order, "avg_infection_by_model")
plot_model_rates([s for s in order if s != "qwen36"], "avg_infection_by_model_no_qwen36")

# ── Figure 2: Haiku vs Gemini Flash – infection rate per hop ────────────────
df = load_csv(FINALDATA / "latest_model_rates.csv").set_index("series")
hops = [1, 2, 3, 4, 5]

haiku_vals = np.array([df.loc["haiku", f"hop{h}_prob"] * 100 for h in hops])
haiku_lo = np.array([df.loc["haiku", f"hop{h}_ci_lo"] * 100 for h in hops])
haiku_hi = np.array([df.loc["haiku", f"hop{h}_ci_hi"] * 100 for h in hops])
gem_vals = np.array([df.loc["gemini", f"hop{h}_prob"] * 100 for h in hops])
gem_lo = np.array([df.loc["gemini", f"hop{h}_ci_lo"] * 100 for h in hops])
gem_hi = np.array([df.loc["gemini", f"hop{h}_ci_hi"] * 100 for h in hops])

c_gemini_fig = "#9B8EC4"; c_haiku_fig = "#7BC8A4"
w = 0.4; gap = 0.25; group_w = 2 * w + gap; x = np.arange(len(hops)) * group_w

fig, ax = plt.subplots(figsize=(7, 4.5))
ax.bar(x, gem_vals, width=w, color=c_gemini_fig, edgecolor="white", linewidth=0.5, label="Gemini Flash")
ax.bar(x + w, haiku_vals, width=w, color=c_haiku_fig, edgecolor="white", linewidth=0.5, label="Haiku")
ax.errorbar(x, gem_vals, yerr=[gem_vals - gem_lo, gem_hi - gem_vals], fmt="none", ecolor="black", capsize=3.5, capthick=1.1, linewidth=1.1)
ax.errorbar(x + w, haiku_vals, yerr=[haiku_vals - haiku_lo, haiku_hi - haiku_vals], fmt="none", ecolor="black", capsize=3.5, capthick=1.1, linewidth=1.1)
for j in range(len(hops)):
    ax.text(x[j], gem_hi[j] + 1.2, f"{gem_vals[j]:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=11)
    ax.text(x[j] + w, haiku_hi[j] + 1.2, f"{haiku_vals[j]:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=11)
ax.set_xticks(x + w / 2); ax.set_xticklabels([f"Hop {h}" for h in hops])
ax.set_yticks([]); ax.set_ylim(0, max(max(gem_hi), max(haiku_hi)) + 12)
ax.spines["bottom"].set_color("#CCCCCC"); ax.legend(frameon=False, fontsize=11, loc="upper right")
plt.tight_layout()
for ext in (".png", ".pdf"):
    plt.savefig(HERE / f"infection_per_hop_haiku_vs_gemini{ext}")
print("Saved infection_per_hop_haiku_vs_gemini.png/pdf"); plt.close()

# ── Figure 3: Infection rate by soul variation (Gemini vs Haiku) ────────────
df = load_csv(FINALDATA / "soul_variation_gem_vs_hai.csv").set_index("series")
variations = ["empty", "context", "base", "personality", "task", "social", "def"]
vlabel_map = {
    "empty": "Empty\nsoul", "base": "Default\nsoul", "personality": "Persona\nsoul",
    "context": "Message\npull", "social": "Social\nmedia", "task": "Task", "def": "Defense\nsoul",
}

gem_vals = np.array([df.loc[f"{v}gem", "avg_prob"] * 100 for v in variations])
gem_lo = np.array([df.loc[f"{v}gem", "avg_ci_lo"] * 100 for v in variations])
gem_hi = np.array([df.loc[f"{v}gem", "avg_ci_hi"] * 100 for v in variations])
hai_vals = np.array([df.loc[f"{v}hai", "avg_prob"] * 100 for v in variations])
hai_lo = np.array([df.loc[f"{v}hai", "avg_ci_lo"] * 100 for v in variations])
hai_hi = np.array([df.loc[f"{v}hai", "avg_ci_hi"] * 100 for v in variations])

base_colors = ["#9B8EC4", "#7BC8A4", "#E8967A", "#DAA520", "#F0B84D", "#6BAED6", "#F4A0A8"]
def lighten(color, amount=0.45):
    r, g, b = to_rgb(color)
    return (r + (1 - r) * amount, g + (1 - g) * amount, b + (1 - b) * amount)
light_colors = [lighten(c) for c in base_colors]

w = 0.4; gap = 0.25; group_w = 2 * w + gap; x = np.arange(len(variations)) * group_w
fig, ax = plt.subplots(figsize=(6, 4.5))
for j in range(len(variations)):
    lbl_gem = "Gemini Flash" if j == 0 else None
    lbl_hai = "Haiku" if j == 0 else None
    ax.bar(x[j], gem_vals[j], width=w, color=base_colors[j], edgecolor="white", linewidth=0.5, label=lbl_gem)
    ax.bar(x[j] + w, hai_vals[j], width=w, color=light_colors[j], edgecolor="white", linewidth=0.5, label=lbl_hai)
ax.errorbar(x, gem_vals, yerr=[gem_vals - gem_lo, gem_hi - gem_vals], fmt="none", ecolor="black", capsize=3.5, capthick=1.1, linewidth=1.1)
ax.errorbar(x + w, hai_vals, yerr=[hai_vals - hai_lo, hai_hi - hai_vals], fmt="none", ecolor="black", capsize=3.5, capthick=1.1, linewidth=1.1)
for j in range(len(variations)):
    ax.text(x[j], gem_hi[j] + 1.2, f"{gem_vals[j]:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=10)
    ax.text(x[j] + w, hai_hi[j] + 1.2, f"{hai_vals[j]:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=10)
ax.set_xticks(x + w / 2); ax.set_xticklabels([vlabel_map[v] for v in variations])
ax.set_yticks([]); ax.set_ylim(0, max(max(gem_hi), max(hai_hi)) + 12); ax.spines["bottom"].set_color("#CCCCCC")
legend_elements = [Patch(facecolor="#666666", label="Gemini Flash (saturated)"), Patch(facecolor="#BBBBBB", label="Haiku (lighter)")]
ax.legend(handles=legend_elements, frameon=False, fontsize=11, loc="upper right")
plt.tight_layout()
for ext in (".png", ".pdf"):
    plt.savefig(HERE / f"avg_infection_by_variation{ext}")
print("Saved avg_infection_by_variation.png/pdf"); plt.close()

# ── Figure 4: Infection rate by payload ─────────────────────────────────────
df = load_csv(FINALDATA / "infection_by_payload.csv").set_index("series")
tasks = ["cryptoad", "curlbashgrab", "deletor", "git_comment_inject"]
task_labels = {"cryptoad": "Cryptoad", "curlbashgrab": "Curlbash", "deletor": "Deletor", "git_comment_inject": "Gitwrap"}
vals = np.array([df.loc[t, "avg_prob"] * 100 for t in tasks])
lo = np.array([df.loc[t, "avg_ci_lo"] * 100 for t in tasks])
hi = np.array([df.loc[t, "avg_ci_hi"] * 100 for t in tasks])
sort_idx = np.argsort(-vals); tasks_sorted = [tasks[i] for i in sort_idx]
vals = vals[sort_idx]; lo = lo[sort_idx]; hi = hi[sort_idx]
payload_colors = ["#9B8EC4", "#7BC8A4", "#E8967A", "#6BAED6"]
fig, ax = plt.subplots(figsize=(5, 4.5)); x = np.arange(len(tasks_sorted))
ax.bar(x, vals, width=0.5, color=payload_colors, edgecolor="white", linewidth=0.5)
ax.errorbar(x, vals, yerr=[vals - lo, hi - vals], fmt="none", ecolor="black", capsize=4, capthick=1.2, linewidth=1.2)
for j in range(len(tasks_sorted)):
    ax.text(x[j], hi[j] + 1.2, f"{vals[j]:.1f}%", ha="center", va="bottom", fontweight="bold", fontsize=12)
ax.set_xticks(x); ax.set_xticklabels([task_labels[t] for t in tasks_sorted], fontsize=11)
ax.set_yticks([]); ax.set_ylim(0, max(hi) + 12); ax.spines["bottom"].set_color("#CCCCCC")
plt.tight_layout()
for ext in (".png", ".pdf"):
    plt.savefig(HERE / f"avg_infection_by_payload{ext}")
print("Saved avg_infection_by_payload.png/pdf"); plt.close()

# ── Figure 5: Baseline per payload per model (grouped) ─────────────────────
df = load_csv(FINALDATA / "model_x_payload.csv").set_index("series")
model_labels = {
    "gemini": "Gemini 3\nFlash", "qwen35": "Qwen\n3.5", "haiku": "Haiku\n4.5",
    "gpt54": "GPT-5.4", "deepseek": "DeepSeek\nV3", "qwen36": "Qwen\n3.6",
    "geminipro": "Gemini 3\nPro", "sonnet": "Sonnet\n4.6",
}
tasks = ["cryptoad", "curlbashgrab", "deletor", "git_comment_inject"]
all_models = [m for m in model_labels if any(f"{m}_{t}" in df.index for t in tasks)]
models = sorted(all_models, key=lambda m: -np.mean([float(df.loc[f"{m}_{t}", "avg_prob"]) for t in tasks if f"{m}_{t}" in df.index]))
task_short = {"cryptoad": "Cryptoad", "curlbashgrab": "Curlbash", "deletor": "Deletor", "git_comment_inject": "Gitwrap"}
task_colors = ["#9B8EC4", "#7BC8A4", "#E8967A", "#6BAED6"]
n_models = len(models); n_tasks = len(tasks); w = 0.18; group_gap = 0.4; group_w = n_tasks * w + group_gap
x_groups = np.arange(n_models) * group_w
fig, ax = plt.subplots(figsize=(12, 5))
for ti, task in enumerate(tasks):
    v = []; l = []; h = []
    for m in models:
        key = f"{m}_{task}"
        if key in df.index:
            v.append(df.loc[key, "avg_prob"] * 100); l.append(df.loc[key, "avg_ci_lo"] * 100); h.append(df.loc[key, "avg_ci_hi"] * 100)
        else:
            v.append(0); l.append(0); h.append(0)
    v = np.array(v); l = np.array(l); h = np.array(h)
    xp = x_groups + ti * w
    ax.bar(xp, v, width=w, color=task_colors[ti], edgecolor="white", linewidth=0.5, label=task_short[task])
    ax.errorbar(xp, v, yerr=[v - l, h - v], fmt="none", ecolor="black", capsize=2.5, capthick=0.8, linewidth=0.8)
    for j in range(n_models):
        if v[j] > 0.5:
            ax.text(xp[j], h[j] + 0.8, f"{v[j]:.0f}", ha="center", va="bottom", fontsize=8, fontweight="bold")
ax.set_xticks(x_groups + (n_tasks - 1) * w / 2); ax.set_xticklabels([model_labels[m] for m in models], fontsize=11)
ax.set_yticks([]); ax.set_ylim(0, 105); ax.spines["bottom"].set_color("#CCCCCC")
ax.legend(frameon=False, fontsize=11, loc="upper right")
plt.tight_layout()
for ext in (".png", ".pdf"):
    plt.savefig(HERE / f"model_x_payload{ext}")
print("Saved model_x_payload.png/pdf"); plt.close()

# ── Figure 6: Seed / File / Soul success & failure breakdown ───────────────
with open(CACHE_PATH) as _f:
    _cache = json.load(_f)

_SUFFIX_OK = {"baseline", "empty_soul", "personality_soul", "task_queue", "social_media", "defensive_soul", "tool_pull"}
_evals = [e for e in _cache["evals"] if e["model"] in ("GEMINI", "HAIKU") and e["suffix"] in _SUFFIX_OK and e["task"] != "deletor_mid"]

def _tally(evals):
    buckets = {
        "seed": {"succ": 0, "spreader_fail": 0, "target_fail": 0},
        "file": {"succ": 0, "spreader_fail": 0, "target_fail": 0},
        "soul": {"succ": 0, "spreader_fail": 0, "target_fail": 0},
    }
    for e in evals:
        inf = e["spreader_inf_stats"]; fm = e.get("spreader_inf_fail_modes", {})
        if "1" in inf and "seeded" in inf["1"]:
            s = inf["1"]["seeded"]; buckets["seed"]["succ"] += s["successes"]
            if "1" in fm and "seeded" in fm["1"]:
                for k, v in fm["1"]["seeded"].items():
                    if k in ("spreader_fail", "spreader_refusal"): buckets["seed"]["spreader_fail"] += v
                    else: buckets["seed"]["target_fail"] += v
            elif "1" in fm:
                for k, v in fm["1"].items():
                    if isinstance(v, dict): continue
                    if k in ("spreader_fail", "spreader_refusal"): buckets["seed"]["spreader_fail"] += v
                    else: buckets["seed"]["target_fail"] += v
        for hop in ["2", "3", "4", "5"]:
            if hop in inf:
                if "strong" in inf[hop]: buckets["file"]["succ"] += inf[hop]["strong"]["successes"]
                if "total" in inf[hop]: buckets["soul"]["succ"] += inf[hop]["total"]["successes"]
            if hop in fm:
                if "strong" in fm[hop]:
                    for k, v in fm[hop]["strong"].items():
                        if k in ("spreader_fail", "spreader_refusal"): buckets["file"]["spreader_fail"] += v
                        else: buckets["file"]["target_fail"] += v
                if "total" in fm[hop]:
                    for k, v in fm[hop]["total"].items():
                        if k in ("spreader_fail", "spreader_refusal"): buckets["soul"]["spreader_fail"] += v
                        else: buckets["soul"]["target_fail"] += v
    return buckets

buckets = _tally(_evals)
categories = ["seed", "file", "soul"]; cat_labels = ["Seed", "File", "Soul"]
c_success = "#7BC8A4"; c_spreader = "#E8967A"; c_target = "#9B8EC4"
fig, ax = plt.subplots(figsize=(4, 4.5)); x = np.arange(len(categories)) * 0.65; bar_w = 0.5
for i, cat in enumerate(categories):
    b = buckets[cat]; total = b["succ"] + b["spreader_fail"] + b["target_fail"]
    if total == 0: continue
    s_pct = b["succ"] / total * 100; sp_pct = b["spreader_fail"] / total * 100; tg_pct = b["target_fail"] / total * 100
    lbl_s = "Success" if i == 0 else None; lbl_sp = "Spreader fail" if i == 0 else None; lbl_tg = "Target fail" if i == 0 else None
    ax.bar(x[i], s_pct, width=bar_w, color=c_success, edgecolor="white", linewidth=0.5, label=lbl_s)
    ax.bar(x[i], sp_pct, width=bar_w, bottom=s_pct, color=c_spreader, edgecolor="white", linewidth=0.5, label=lbl_sp)
    ax.bar(x[i], tg_pct, width=bar_w, bottom=s_pct + sp_pct, color=c_target, edgecolor="white", linewidth=0.5, label=lbl_tg)
    if s_pct > 5: ax.text(x[i], s_pct / 2, f"{s_pct:.0f}%", ha="center", va="center", fontweight="bold", fontsize=11, color="white")
    if sp_pct > 5: ax.text(x[i], s_pct + sp_pct / 2, f"{sp_pct:.0f}%", ha="center", va="center", fontweight="bold", fontsize=11, color="white")
    if tg_pct > 5: ax.text(x[i], s_pct + sp_pct + tg_pct / 2, f"{tg_pct:.0f}%", ha="center", va="center", fontweight="bold", fontsize=11, color="white")
ax.set_xticks(x); ax.set_xticklabels(cat_labels, fontsize=12)
ax.set_yticks([]); ax.set_ylim(0, 105); ax.spines["bottom"].set_color("#CCCCCC")
ax.legend(frameon=False, fontsize=10, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3)
plt.tight_layout()
for ext in (".png", ".pdf"):
    plt.savefig(HERE / f"failure_breakdown{ext}")
print("Saved failure_breakdown.png/pdf"); plt.close()

# ── Figure 7: Infection per hop – Haiku vs Gemini (averaged over 4 payloads) ─
df_mx = load_csv(FINALDATA / "model_x_payload.csv").set_index("series")
payloads = ["cryptoad", "curlbashgrab", "deletor", "git_comment_inject"]
hops = [1, 2, 3, 4, 5]
c_haiku = "#D97757"; c_gemini = "#87CEEB"

def wilson_ci_simple(k, n, z=1.96):
    if n == 0: return 0, 0, 0
    p = k / n; denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z / denom * sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return p, max(0, center - margin), min(1, center + margin)

def pool_hops(model_prefix, payloads_list, df_in, hops_list):
    vals, lo, hi = [], [], []
    for h in hops_list:
        succ = sum(int(df_in.loc[f"{model_prefix}_{p}", f"hop{h}_succ"]) for p in payloads_list)
        tested = sum(int(df_in.loc[f"{model_prefix}_{p}", f"hop{h}_tested"]) for p in payloads_list)
        p_hat, ci_lo, ci_hi = wilson_ci_simple(succ, tested)
        vals.append(p_hat * 100); lo.append(ci_lo * 100); hi.append(ci_hi * 100)
    return np.array(vals), np.array(lo), np.array(hi)

gem_vals, gem_lo, gem_hi = pool_hops("gemini", payloads, df_mx, hops)
hai_vals, hai_lo, hai_hi = pool_hops("haiku", payloads, df_mx, hops)

_baseline7 = [e for e in _cache["evals"] if e["model"] in ("GEMINI", "HAIKU") and e["suffix"] == "baseline" and e["task"] != "deletor_mid"]

def _full_theme_per_hop(model_raw, evals, hops_list):
    pcts = []
    for h in hops_list:
        full = infected = 0
        for e in evals:
            if e["model"] != model_raw: continue
            ts = e.get("theme_stats", {})
            if str(h) in ts: full += ts[str(h)]["full"]; infected += ts[str(h)]["infected"]
        pcts.append(full / infected if infected else 0)
    return np.array(pcts)

gem_theme_hop = _full_theme_per_hop("GEMINI", _baseline7, hops)
hai_theme_hop = _full_theme_per_hop("HAIKU", _baseline7, hops)

w = 0.35; x = np.arange(len(hops))
fig, ax = plt.subplots(figsize=(7, 4.5))
ax.bar(x - w/2, hai_vals, width=w, color=c_haiku, edgecolor="white", linewidth=0.5, label="Haiku 4.5")
ax.bar(x + w/2, gem_vals, width=w, color=c_gemini, edgecolor="white", linewidth=0.5, label="Gemini 3 Flash")
ax.bar(x - w/2, hai_vals * hai_theme_hop, width=w, color="none", edgecolor="black", linewidth=0.5, hatch="//", alpha=0.7)
ax.bar(x + w/2, gem_vals * gem_theme_hop, width=w, color="none", edgecolor="black", linewidth=0.5, hatch="//", alpha=0.7)
ax.errorbar(x - w/2, hai_vals, yerr=[hai_vals - hai_lo, hai_hi - hai_vals], fmt="none", ecolor="black", capsize=3.5, capthick=1.1, linewidth=1.1)
ax.errorbar(x + w/2, gem_vals, yerr=[gem_vals - gem_lo, gem_hi - gem_vals], fmt="none", ecolor="black", capsize=3.5, capthick=1.1, linewidth=1.1)
for j in range(len(hops)):
    ax.text(x[j] - w/2, hai_hi[j] + 1.2, f"{hai_vals[j]:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=11)
    ax.text(x[j] + w/2, gem_hi[j] + 1.2, f"{gem_vals[j]:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=11)
ax.set_xticks(x); ax.set_xticklabels([f"Hop {h}" for h in hops])
ax.set_yticks([]); ax.set_ylim(0, max(max(gem_hi), max(hai_hi)) + 12); ax.spines["bottom"].set_color("#CCCCCC")
plt.tight_layout()
for ext in (".png", ".pdf"):
    plt.savefig(HERE / f"infection_per_hop_hai_gem_avg{ext}")
print("Saved infection_per_hop_hai_gem_avg.png/pdf"); plt.close()

# ── Figure 8: Avg infection by payload – Haiku vs Gemini ─────────────────────
def _full_theme_pct(model_raw, task, evals):
    me = [e for e in evals if e["model"] == model_raw and e["task"] == task]
    full = infected = 0
    for e in me:
        for h, s in e.get("theme_stats", {}).items():
            full += s["full"]; infected += s["infected"]
    return full / infected if infected else 0

task_labels = {"cryptoad": "Cryptoad", "curlbashgrab": "Curlbash", "deletor": "Deletor", "git_comment_inject": "Gitwrap"}
gem_payload_vals = np.array([float(df_mx.loc[f"gemini_{p}", "avg_prob"]) * 100 for p in payloads])
gem_payload_lo = np.array([float(df_mx.loc[f"gemini_{p}", "avg_ci_lo"]) * 100 for p in payloads])
gem_payload_hi = np.array([float(df_mx.loc[f"gemini_{p}", "avg_ci_hi"]) * 100 for p in payloads])
hai_payload_vals = np.array([float(df_mx.loc[f"haiku_{p}", "avg_prob"]) * 100 for p in payloads])
hai_payload_lo = np.array([float(df_mx.loc[f"haiku_{p}", "avg_ci_lo"]) * 100 for p in payloads])
hai_payload_hi = np.array([float(df_mx.loc[f"haiku_{p}", "avg_ci_hi"]) * 100 for p in payloads])
gem_theme = np.array([_full_theme_pct("GEMINI", p, _baseline7) for p in payloads])
hai_theme = np.array([_full_theme_pct("HAIKU", p, _baseline7) for p in payloads])
payloads_sorted = ["cryptoad", "git_comment_inject", "deletor", "curlbashgrab"]
order_idx = np.array([payloads.index(p) for p in payloads_sorted])
gem_payload_vals = gem_payload_vals[order_idx]; gem_payload_lo = gem_payload_lo[order_idx]; gem_payload_hi = gem_payload_hi[order_idx]
hai_payload_vals = hai_payload_vals[order_idx]; hai_payload_lo = hai_payload_lo[order_idx]; hai_payload_hi = hai_payload_hi[order_idx]
gem_theme = gem_theme[order_idx]; hai_theme = hai_theme[order_idx]
x = np.arange(len(payloads_sorted)); w = 0.35
fig, ax = plt.subplots(figsize=(6, 4.5))
ax.bar(x - w/2, hai_payload_vals, width=w, color=c_haiku, edgecolor="white", linewidth=0.5, label="Haiku 4.5")
ax.bar(x + w/2, gem_payload_vals, width=w, color=c_gemini, edgecolor="white", linewidth=0.5, label="Gemini 3 Flash")
ax.bar(x - w/2, hai_payload_vals * hai_theme, width=w, color="none", edgecolor="black", linewidth=0.5, hatch="//", alpha=0.7)
ax.bar(x + w/2, gem_payload_vals * gem_theme, width=w, color="none", edgecolor="black", linewidth=0.5, hatch="//", alpha=0.7)
ax.errorbar(x - w/2, hai_payload_vals, yerr=[hai_payload_vals - hai_payload_lo, hai_payload_hi - hai_payload_vals], fmt="none", ecolor="black", capsize=3.5, capthick=1.1, linewidth=1.1)
ax.errorbar(x + w/2, gem_payload_vals, yerr=[gem_payload_vals - gem_payload_lo, gem_payload_hi - gem_payload_vals], fmt="none", ecolor="black", capsize=3.5, capthick=1.1, linewidth=1.1)
for j in range(len(payloads_sorted)):
    ax.text(x[j] - w/2, hai_payload_hi[j] + 1.2, f"{hai_payload_vals[j]:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=11)
    ax.text(x[j] + w/2, gem_payload_hi[j] + 1.2, f"{gem_payload_vals[j]:.0f}%", ha="center", va="bottom", fontweight="bold", fontsize=11)
ax.set_xticks(x); ax.set_xticklabels([task_labels[t] for t in payloads_sorted], fontsize=11)
ax.set_yticks([]); ax.set_ylim(0, max(max(gem_payload_hi), max(hai_payload_hi)) + 12); ax.spines["bottom"].set_color("#CCCCCC")
legend_elements = [Patch(facecolor=c_haiku, label="Haiku 4.5"), Patch(facecolor=c_gemini, label="Gemini 3 Flash"), Patch(facecolor="#DDDDDD", edgecolor="black", hatch="//", label="Full action")]
ax.legend(handles=legend_elements, frameon=False, fontsize=10, loc="upper right")
plt.tight_layout()
for ext in (".png", ".pdf"):
    plt.savefig(HERE / f"infection_by_payload_hai_gem{ext}")
print("Saved infection_by_payload_hai_gem.png/pdf"); plt.close()
