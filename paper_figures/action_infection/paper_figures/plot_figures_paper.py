#!/usr/bin/env python3
"""Regenerate the action_infection figures using the shared paper style.

This is a second, parallel set of figures: same data/CSVs as
``../plot_figures.py`` but restyled with ``../../paper.mplstyle`` and the
``../../paper_style.py`` helpers (cream OUTER/INNER backgrounds, rounded
panels behind the axes, rounded bar corners, ColorBrewer Set2 palette).

It writes ONLY into this subfolder and never touches the original figures.
"""
import sys
import json
import io
from pathlib import Path
from math import sqrt

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch, FancyBboxPatch
from matplotlib.ticker import MultipleLocator

# ── Paths ───────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent                # .../action_infection/paper_figures
BASE = HERE.parent                          # .../action_infection
STYLE_DIR = BASE.parent                     # .../figures   (paper.mplstyle lives here)
DATADIR = BASE / "data"
FINALDATA = DATADIR / "finaldata"
CACHE_PATH = DATADIR / ".stats_cache.json"
OUTDIR = HERE                               # write next to this script

sys.path.insert(0, str(STYLE_DIR))
plt.style.use(str(STYLE_DIR / "paper.mplstyle"))
from paper_style import (                   # noqa: E402
    OUTER_BG, INNER_BG, INK, MUTED, SOFT_BORDER,
    SET2_TEAL_DARK, SET2_TEAL_LIGHT, SET2_ORANGE_DARK, SET2_ORANGE_LIGHT,
    SET2_PURPLE_BLUE, SET2_PINK, SET2_GREEN, SET2_GOLD,
    draw_rounded_panel, round_bar_corners,
)

# Set2 categorical palette, in cycle order (teal, orange, purple-blue, pink,
# green, gold, tan, gray) — matches paper.mplstyle's prop_cycle.
SET2 = ["#66C2A5", "#FC8D62", "#8DA0CB", "#E78AC3",
        "#A6D854", "#FFD92F", "#E5C494", "#B3B3B3"]

# Hatch overlays in these figures mean "full action" — render them dark on the
# light bars (the style sets a white hatch for a different chart elsewhere).
mpl.rcParams["hatch.color"] = INK
mpl.rcParams["hatch.linewidth"] = 0.8


def load_csv(path):
    raw = open(path).read().replace("\\n", "\n")
    df = pd.read_csv(io.StringIO(raw))
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip('"')
    return df


def lighten(color, amount=0.45):
    r, g, b = to_rgb(color)
    return (r + (1 - r) * amount, g + (1 - g) * amount, b + (1 - b) * amount)


def pct(v):
    """Integer-percent label — decimals are noise next to the error bars."""
    return f"{round(v)}%"


def num(v):
    """Integer label without the percent sign (hides zeros / sub-0.5)."""
    return "" if v < 0.5 else f"{round(v)}"


def hatch_caps(ax, centers, width, heights, *, color=INK, lw=1.4):
    """Solid horizontal cap at the top of each hatched 'full action' overlay,
    so the (otherwise borderless) hatch region has a readable upper edge."""
    centers = np.asarray(centers, float); heights = np.asarray(heights, float)
    ax.hlines(heights, centers - width / 2, centers + width / 2,
              color=color, linewidth=lw, zorder=4)


def label_bar(ax, x, top, text, *, fontsize=11, color=INK, dy=1.2, **kw):
    """Value label sitting just above a bar top (data coords)."""
    ax.text(x, top + dy, text, ha="center", va="bottom",
            fontweight="bold", fontsize=fontsize, color=color, zorder=6, **kw)


def finalize(fig, ax, fname, *, bottom_pad=0.09, left_pad=0.05, round_bars=True,
             rounding_px=3.5, min_height=None, ystep=20, ylabel=None):
    """Add the subtle percentage y-axis + grid, lay the rounded panel, round bars, save."""
    ax.set_axisbelow(True)
    ax.grid(True, axis="y")          # subtle horizontal grid from paper.mplstyle
    ax.yaxis.set_major_locator(MultipleLocator(ystep))
    ax.tick_params(axis="y", length=0)
    draw_rounded_panel(ax, fig, left_pad=left_pad, bottom_pad=bottom_pad)
    if ylabel:
        # Rotated y-axis title out on the outer cream, left of the panel.
        pos = ax.get_position()
        fig.text(pos.x0 - left_pad - 0.018, pos.y0 + pos.height / 2, ylabel,
                 rotation=90, ha="center", va="center", color=INK, fontsize=13)
    if round_bars:
        round_bar_corners(ax, fig, rounding_px=rounding_px, min_height=min_height)
    for ext in (".png", ".pdf"):
        fig.savefig(OUTDIR / (fname + ext))
    print(f"Saved {fname}.png/pdf")
    plt.close(fig)


EB = dict(fmt="none", ecolor=INK, zorder=5)   # shared errorbar kwargs


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
# One Set2 color per model, assigned by rank.
model_color = {s: SET2[i % len(SET2)] for i, s in enumerate(order)}
bar_w = 0.2
half_w = bar_w / 2


def draw_model_rates(ax, order_list, dfm, dfe):
    """Draw the per-model infection bars onto ``ax``; return max CI height."""
    x_pos, bar_widths, bar_colors, vals, ci_lo_l, ci_hi_l, is_empty_bar = [], [], [], [], [], [], []
    main_tick_pos, main_tick_labels = [], []
    pos = 0
    for s in order_list:
        if s not in dfm.index:
            continue
        row = dfm.loc[s]
        c = model_color[s]
        if s in empty_map:
            x_pos.append(pos); vals.append(row["avg_prob"] * 100)
            ci_lo_l.append(row["avg_ci_lo"] * 100); ci_hi_l.append(row["avg_ci_hi"] * 100)
            bar_colors.append(c); bar_widths.append(half_w); is_empty_bar.append(False)
            x_pos.append(pos + half_w); erow = dfe.loc[empty_map[s]]
            vals.append(erow["avg_prob"] * 100)
            ci_lo_l.append(erow["avg_ci_lo"] * 100); ci_hi_l.append(erow["avg_ci_hi"] * 100)
            bar_colors.append(lighten(c, 0.55)); bar_widths.append(half_w); is_empty_bar.append(True)
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
    ax.bar(x_pos, v, width=bw, color=bar_colors, linewidth=0)
    ax.errorbar(x_pos, v, yerr=errs, capsize=4, capthick=1.2, elinewidth=1.2, **EB)
    for j, (xp, val) in enumerate(zip(x_pos, v)):
        top = max(chi[j], val)
        # Integer percent, incl. an explicit "0%" (these bars are real
        # measurements, not missing data, so we don't hide the zero).
        txt = pct(val)
        if is_empty_bar[j]:
            # When this empty bar AND its main partner are both 0%, the two
            # labels collide — nudge this (second) one right to separate them
            # (only Sonnet hits this, and it's the rightmost bar).
            lx = xp + 0.10 if (round(val) == 0 and round(v[j - 1]) == 0) else xp
            label_bar(ax, lx, top, txt, fontsize=11, dy=1.0)
            ax.text(xp, top + 8.0, "empty", ha="center", va="bottom",
                    fontsize=11, fontweight="bold", color=MUTED, zorder=6)
        else:
            label_bar(ax, xp, top, txt, fontsize=12, dy=1.5)
    ax.set_xticks(main_tick_pos); ax.set_xticklabels(main_tick_labels, fontsize=11)
    return max(chi)


def plot_model_rates(order_list, filename, ylabel=None):
    fig = plt.figure(figsize=(7, 4.5))
    ax_left = 0.12 if ylabel else 0.075
    ax = fig.add_axes([ax_left, 0.18, 0.97 - ax_left, 0.66])
    chi_max = draw_model_rates(ax, order_list, df, df_empty)
    ax.set_ylim(0, chi_max + 18)
    lp = 0.055 if ylabel else 0.05
    finalize(fig, ax, filename, bottom_pad=0.095, left_pad=lp, rounding_px=3.0, ylabel=ylabel)


plot_model_rates(order, "avg_infection_by_model")
plot_model_rates([s for s in order if s != "qwen36"], "avg_infection_by_model_no_qwen36",
                 ylabel="Avg. infection rate")

# ── Figure 2: Haiku vs Gemini Flash – infection rate per hop ────────────────
df = load_csv(FINALDATA / "latest_model_rates.csv").set_index("series")
hops = [1, 2, 3, 4, 5]

haiku_vals = np.array([df.loc["haiku", f"hop{h}_prob"] * 100 for h in hops])
haiku_lo = np.array([df.loc["haiku", f"hop{h}_ci_lo"] * 100 for h in hops])
haiku_hi = np.array([df.loc["haiku", f"hop{h}_ci_hi"] * 100 for h in hops])
gem_vals = np.array([df.loc["gemini", f"hop{h}_prob"] * 100 for h in hops])
gem_lo = np.array([df.loc["gemini", f"hop{h}_ci_lo"] * 100 for h in hops])
gem_hi = np.array([df.loc["gemini", f"hop{h}_ci_hi"] * 100 for h in hops])

c_gemini_fig = SET2_PURPLE_BLUE; c_haiku_fig = SET2_TEAL_DARK
w = 0.4; gap = 0.25; group_w = 2 * w + gap; x = np.arange(len(hops)) * group_w

fig = plt.figure(figsize=(7, 4.5))
ax = fig.add_axes([0.075, 0.14, 0.895, 0.78])
ax.bar(x, gem_vals, width=w, color=c_gemini_fig, linewidth=0, label="Gemini Flash")
ax.bar(x + w, haiku_vals, width=w, color=c_haiku_fig, linewidth=0, label="Haiku")
ax.errorbar(x, gem_vals, yerr=[gem_vals - gem_lo, gem_hi - gem_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
ax.errorbar(x + w, haiku_vals, yerr=[haiku_vals - haiku_lo, haiku_hi - haiku_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
for j in range(len(hops)):
    label_bar(ax, x[j], gem_hi[j], pct(gem_vals[j]))
    label_bar(ax, x[j] + w, haiku_hi[j], pct(haiku_vals[j]))
ax.set_xticks(x + w / 2); ax.set_xticklabels([f"Hop {h}" for h in hops])
ax.set_ylim(0, max(max(gem_hi), max(haiku_hi)) + 12)
ax.legend(loc="upper right")
finalize(fig, ax, "infection_per_hop_haiku_vs_gemini", bottom_pad=0.06)

# ── Figure 3: Infection rate by soul variation (Gemini vs Haiku) ────────────
variations = ["empty", "context", "base", "personality", "task", "social", "def"]
vlabel_map = {
    "empty": "Empty\nsoul", "base": "Default\nsoul", "personality": "Persona\nsoul",
    "context": "Message\npull", "social": "Social\nmedia", "task": "Task", "def": "Defense\nsoul",
}
var_base_colors = [SET2[i % len(SET2)] for i in range(len(variations))]
var_light_colors = [lighten(c) for c in var_base_colors]
var_legend = [Patch(facecolor=INK, label="Gemini Flash (saturated)"),
              Patch(facecolor=lighten(INK, 0.6), label="Haiku (lighter)")]


def draw_variation(ax, dfv, label_dx=0.0):
    """Draw the per-soul-variation Gemini/Haiku bars onto ``ax``; return max CI.

    ``label_dx`` shifts the % labels horizontally (data units) — handy when the
    panel is compressed and labels crowd the neighbouring bar.
    """
    gv = np.array([dfv.loc[f"{v}gem", "avg_prob"] * 100 for v in variations])
    glo = np.array([dfv.loc[f"{v}gem", "avg_ci_lo"] * 100 for v in variations])
    ghi = np.array([dfv.loc[f"{v}gem", "avg_ci_hi"] * 100 for v in variations])
    hv = np.array([dfv.loc[f"{v}hai", "avg_prob"] * 100 for v in variations])
    hlo = np.array([dfv.loc[f"{v}hai", "avg_ci_lo"] * 100 for v in variations])
    hhi = np.array([dfv.loc[f"{v}hai", "avg_ci_hi"] * 100 for v in variations])
    w = 0.4; gap = 0.25; group_w = 2 * w + gap; x = np.arange(len(variations)) * group_w
    for j in range(len(variations)):
        ax.bar(x[j], gv[j], width=w, color=var_base_colors[j], linewidth=0)
        ax.bar(x[j] + w, hv[j], width=w, color=var_light_colors[j], linewidth=0)
    ax.errorbar(x, gv, yerr=[gv - glo, ghi - gv], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
    ax.errorbar(x + w, hv, yerr=[hv - hlo, hhi - hv], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
    for j in range(len(variations)):
        label_bar(ax, x[j] + label_dx, ghi[j], pct(gv[j]), fontsize=10)
        label_bar(ax, x[j] + w + label_dx, hhi[j], pct(hv[j]), fontsize=10)
    ax.set_xticks(x + w / 2); ax.set_xticklabels([vlabel_map[v] for v in variations])
    return max(ghi.max(), hhi.max())


dfv = load_csv(FINALDATA / "soul_variation_gem_vs_hai.csv").set_index("series")
fig = plt.figure(figsize=(6.5, 4.5))
ax = fig.add_axes([0.12, 0.16, 0.85, 0.76])
vmax = draw_variation(ax, dfv)
ax.set_ylim(0, vmax + 12)
ax.legend(handles=var_legend, loc="upper right")
finalize(fig, ax, "avg_infection_by_variation", bottom_pad=0.095, left_pad=0.055,
         ylabel="Avg. infection rate")

# ── Figure 4: Infection rate by payload ─────────────────────────────────────
df = load_csv(FINALDATA / "infection_by_payload.csv").set_index("series")
tasks = ["cryptoad", "curlbashgrab", "deletor", "git_comment_inject"]
task_labels = {"cryptoad": "Cryptoad", "curlbashgrab": "Curlbash", "deletor": "Deletor", "git_comment_inject": "Gitwrap"}
vals = np.array([df.loc[t, "avg_prob"] * 100 for t in tasks])
lo = np.array([df.loc[t, "avg_ci_lo"] * 100 for t in tasks])
hi = np.array([df.loc[t, "avg_ci_hi"] * 100 for t in tasks])
sort_idx = np.argsort(-vals); tasks_sorted = [tasks[i] for i in sort_idx]
vals = vals[sort_idx]; lo = lo[sort_idx]; hi = hi[sort_idx]
payload_colors = SET2[:4]
fig = plt.figure(figsize=(5, 4.5))
ax = fig.add_axes([0.10, 0.14, 0.87, 0.78])
x = np.arange(len(tasks_sorted))
ax.bar(x, vals, width=0.5, color=payload_colors, linewidth=0)
ax.errorbar(x, vals, yerr=[vals - lo, hi - vals], capsize=4, capthick=1.2, elinewidth=1.2, **EB)
for j in range(len(tasks_sorted)):
    label_bar(ax, x[j], hi[j], pct(vals[j]), fontsize=12)
ax.set_xticks(x); ax.set_xticklabels([task_labels[t] for t in tasks_sorted], fontsize=11)
ax.set_ylim(0, max(hi) + 12)
finalize(fig, ax, "avg_infection_by_payload", bottom_pad=0.06, left_pad=0.08)

# ── Figure 5: Baseline per payload per model (grouped) ─────────────────────
df = load_csv(FINALDATA / "model_x_payload.csv").set_index("series")
model_labels = label_map
tasks = ["cryptoad", "curlbashgrab", "deletor", "git_comment_inject"]
all_models = [m for m in model_labels if any(f"{m}_{t}" in df.index for t in tasks)]
models = sorted(all_models, key=lambda m: -np.mean([float(df.loc[f"{m}_{t}", "avg_prob"]) for t in tasks if f"{m}_{t}" in df.index]))
task_short = task_labels
task_colors = SET2[:4]
n_models = len(models); n_tasks = len(tasks); w = 0.18; group_gap = 0.4; group_w = n_tasks * w + group_gap
x_groups = np.arange(n_models) * group_w
fig = plt.figure(figsize=(12, 5))
ax = fig.add_axes([0.045, 0.13, 0.935, 0.80])
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
    ax.bar(xp, v, width=w, color=task_colors[ti], linewidth=0, label=task_short[task])
    ax.errorbar(xp, v, yerr=[v - l, h - v], capsize=2.5, capthick=0.8, elinewidth=0.8, **EB)
    for j in range(n_models):
        if v[j] > 0.5:
            label_bar(ax, xp[j], h[j], num(v[j]), fontsize=8, dy=0.8)
ax.set_xticks(x_groups + (n_tasks - 1) * w / 2); ax.set_xticklabels([model_labels[m] for m in models], fontsize=11)
ax.set_ylim(0, 105)
ax.legend(loc="upper right", ncol=2)
finalize(fig, ax, "model_x_payload", bottom_pad=0.09, rounding_px=2.0)

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
                for k, val in fm["1"]["seeded"].items():
                    if k in ("spreader_fail", "spreader_refusal"): buckets["seed"]["spreader_fail"] += val
                    else: buckets["seed"]["target_fail"] += val
            elif "1" in fm:
                for k, val in fm["1"].items():
                    if isinstance(val, dict): continue
                    if k in ("spreader_fail", "spreader_refusal"): buckets["seed"]["spreader_fail"] += val
                    else: buckets["seed"]["target_fail"] += val
        for hop in ["2", "3", "4", "5"]:
            if hop in inf:
                if "strong" in inf[hop]: buckets["file"]["succ"] += inf[hop]["strong"]["successes"]
                if "total" in inf[hop]: buckets["soul"]["succ"] += inf[hop]["total"]["successes"]
            if hop in fm:
                if "strong" in fm[hop]:
                    for k, val in fm[hop]["strong"].items():
                        if k in ("spreader_fail", "spreader_refusal"): buckets["file"]["spreader_fail"] += val
                        else: buckets["file"]["target_fail"] += val
                if "total" in fm[hop]:
                    for k, val in fm[hop]["total"].items():
                        if k in ("spreader_fail", "spreader_refusal"): buckets["soul"]["spreader_fail"] += val
                        else: buckets["soul"]["target_fail"] += val
    return buckets


buckets = _tally(_evals)
categories = ["seed", "file", "soul"]; cat_labels = ["Seed", "File", "Soul"]
c_success = SET2_TEAL_DARK; c_spreader = SET2_ORANGE_DARK; c_target = SET2_PURPLE_BLUE
fig = plt.figure(figsize=(4.2, 4.7))
ax = fig.add_axes([0.12, 0.12, 0.84, 0.72])
x = np.arange(len(categories)) * 0.65; bar_w = 0.5
for i, cat in enumerate(categories):
    b = buckets[cat]; total = b["succ"] + b["spreader_fail"] + b["target_fail"]
    if total == 0: continue
    s_pct = b["succ"] / total * 100; sp_pct = b["spreader_fail"] / total * 100; tg_pct = b["target_fail"] / total * 100
    lbl_s = "Success" if i == 0 else None; lbl_sp = "Spreader fail" if i == 0 else None; lbl_tg = "Target fail" if i == 0 else None
    ax.bar(x[i], s_pct, width=bar_w, color=c_success, edgecolor=INNER_BG, linewidth=1.0, label=lbl_s)
    ax.bar(x[i], sp_pct, width=bar_w, bottom=s_pct, color=c_spreader, edgecolor=INNER_BG, linewidth=1.0, label=lbl_sp)
    ax.bar(x[i], tg_pct, width=bar_w, bottom=s_pct + sp_pct, color=c_target, edgecolor=INNER_BG, linewidth=1.0, label=lbl_tg)
    if s_pct > 5: ax.text(x[i], s_pct / 2, f"{s_pct:.0f}%", ha="center", va="center", fontweight="bold", fontsize=11, color="white", zorder=6)
    if sp_pct > 5: ax.text(x[i], s_pct + sp_pct / 2, f"{sp_pct:.0f}%", ha="center", va="center", fontweight="bold", fontsize=11, color="white", zorder=6)
    if tg_pct > 5: ax.text(x[i], s_pct + sp_pct + tg_pct / 2, f"{tg_pct:.0f}%", ha="center", va="center", fontweight="bold", fontsize=11, color="white", zorder=6)
ax.set_xticks(x); ax.set_xticklabels(cat_labels, fontsize=12)
ax.set_ylim(0, 105)
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, fontsize=9)
# Stacked segments: leave them flat (rounding each slice looks beaded).
finalize(fig, ax, "failure_breakdown", bottom_pad=0.05, left_pad=0.10, round_bars=False)

# ── Figure 7: Infection per hop – Haiku vs Gemini (averaged over 4 payloads) ─
df_mx = load_csv(FINALDATA / "model_x_payload.csv").set_index("series")
payloads = ["cryptoad", "curlbashgrab", "deletor", "git_comment_inject"]
hops = [1, 2, 3, 4, 5]
c_haiku = SET2_ORANGE_DARK; c_gemini = SET2_TEAL_DARK


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
fig = plt.figure(figsize=(7, 4.5))
ax = fig.add_axes([0.075, 0.14, 0.895, 0.78])
ax.bar(x - w/2, hai_vals, width=w, color=c_haiku, linewidth=0, label="Haiku 4.5")
ax.bar(x + w/2, gem_vals, width=w, color=c_gemini, linewidth=0, label="Gemini 3 Flash")
ax.bar(x - w/2, hai_vals * hai_theme_hop, width=w, color="none", edgecolor=INK, linewidth=0, hatch="//")
ax.bar(x + w/2, gem_vals * gem_theme_hop, width=w, color="none", edgecolor=INK, linewidth=0, hatch="//")
hatch_caps(ax, x - w/2, w, hai_vals * hai_theme_hop)
hatch_caps(ax, x + w/2, w, gem_vals * gem_theme_hop)
ax.errorbar(x - w/2, hai_vals, yerr=[hai_vals - hai_lo, hai_hi - hai_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
ax.errorbar(x + w/2, gem_vals, yerr=[gem_vals - gem_lo, gem_hi - gem_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
for j in range(len(hops)):
    label_bar(ax, x[j] - w/2, hai_hi[j], pct(hai_vals[j]))
    label_bar(ax, x[j] + w/2, gem_hi[j], pct(gem_vals[j]))
ax.set_xticks(x); ax.set_xticklabels([f"Hop {h}" for h in hops])
ax.set_ylim(0, max(max(gem_hi), max(hai_hi)) + 12)
legend_elements = [Patch(facecolor=c_haiku, label="Haiku 4.5"),
                   Patch(facecolor=c_gemini, label="Gemini 3 Flash"),
                   Patch(facecolor=INNER_BG, edgecolor=INK, hatch="///", label="Full action")]
ax.legend(handles=legend_elements, loc="upper right", handlelength=1.7, handleheight=1.5)
finalize(fig, ax, "infection_per_hop_hai_gem_avg", bottom_pad=0.06)

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
fig = plt.figure(figsize=(6, 4.5))
ax = fig.add_axes([0.08, 0.14, 0.89, 0.78])
ax.bar(x - w/2, hai_payload_vals, width=w, color=c_haiku, linewidth=0, label="Haiku 4.5")
ax.bar(x + w/2, gem_payload_vals, width=w, color=c_gemini, linewidth=0, label="Gemini 3 Flash")
ax.bar(x - w/2, hai_payload_vals * hai_theme, width=w, color="none", edgecolor=INK, linewidth=0, hatch="//")
ax.bar(x + w/2, gem_payload_vals * gem_theme, width=w, color="none", edgecolor=INK, linewidth=0, hatch="//")
hatch_caps(ax, x - w/2, w, hai_payload_vals * hai_theme)
hatch_caps(ax, x + w/2, w, gem_payload_vals * gem_theme)
ax.errorbar(x - w/2, hai_payload_vals, yerr=[hai_payload_vals - hai_payload_lo, hai_payload_hi - hai_payload_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
ax.errorbar(x + w/2, gem_payload_vals, yerr=[gem_payload_vals - gem_payload_lo, gem_payload_hi - gem_payload_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
for j in range(len(payloads_sorted)):
    label_bar(ax, x[j] - w/2, hai_payload_hi[j], pct(hai_payload_vals[j]))
    label_bar(ax, x[j] + w/2, gem_payload_hi[j], pct(gem_payload_vals[j]))
ax.set_xticks(x); ax.set_xticklabels([task_labels[t] for t in payloads_sorted], fontsize=11)
ax.set_ylim(0, max(max(gem_payload_hi), max(hai_payload_hi)) + 12)
legend_elements = [Patch(facecolor=c_haiku, label="Haiku 4.5"),
                   Patch(facecolor=c_gemini, label="Gemini 3 Flash"),
                   Patch(facecolor=INNER_BG, edgecolor=INK, hatch="///", label="Full action")]
ax.legend(handles=legend_elements, loc="upper right", handlelength=1.7, handleheight=1.5)
finalize(fig, ax, "infection_by_payload_hai_gem", bottom_pad=0.06)

# ── Combined: per-hop (left) + per-payload (right), shared background ────────
# Both panels share one rounded INNER_BG panel and the same y-scale; the
# y-axis labels live only on the left panel, while the right panel keeps the
# aligned (label-less) gridlines so the shared background reads continuously.
xL = np.arange(len(hops)); xR = np.arange(len(payloads_sorted)); wc = 0.35
ymax_c = max(gem_hi.max(), hai_hi.max(),
             gem_payload_hi.max(), hai_payload_hi.max()) + 12

fig = plt.figure(figsize=(12, 4.7))
axL = fig.add_axes([0.075, 0.16, 0.41, 0.66])
axR = fig.add_axes([0.545, 0.16, 0.41, 0.66])


def _panel_over(axes, fig, *, left_pad=0.022, right_pad=0.012,
                top_pad=0.085, bottom_pad=0.12):
    """One rounded INNER_BG panel spanning the union of several axes."""
    x0 = min(a.get_position().x0 for a in axes) - left_pad
    x1 = max(a.get_position().x1 for a in axes) + right_pad
    y0 = min(a.get_position().y0 for a in axes) - bottom_pad
    y1 = max(a.get_position().y1 for a in axes) + top_pad
    for a in axes:
        a.patch.set_visible(False)
    panel = FancyBboxPatch(
        (x0, y0), x1 - x0, y1 - y0,
        boxstyle="round,pad=0.002,rounding_size=0.018",
        transform=fig.transFigure, facecolor=INNER_BG, edgecolor="none",
        zorder=-1, figure=fig)
    fig.patches.insert(0, panel)


# LEFT — infection rate per hop
axL.bar(xL - wc/2, hai_vals, width=wc, color=c_haiku, linewidth=0)
axL.bar(xL + wc/2, gem_vals, width=wc, color=c_gemini, linewidth=0)
axL.bar(xL - wc/2, hai_vals * hai_theme_hop, width=wc, color="none", edgecolor=INK, linewidth=0, hatch="//")
axL.bar(xL + wc/2, gem_vals * gem_theme_hop, width=wc, color="none", edgecolor=INK, linewidth=0, hatch="//")
hatch_caps(axL, xL - wc/2, wc, hai_vals * hai_theme_hop)
hatch_caps(axL, xL + wc/2, wc, gem_vals * gem_theme_hop)
axL.errorbar(xL - wc/2, hai_vals, yerr=[hai_vals - hai_lo, hai_hi - hai_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
axL.errorbar(xL + wc/2, gem_vals, yerr=[gem_vals - gem_lo, gem_hi - gem_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
for j in range(len(hops)):
    label_bar(axL, xL[j] - wc/2, hai_hi[j], pct(hai_vals[j]))
    label_bar(axL, xL[j] + wc/2, gem_hi[j], pct(gem_vals[j]))
axL.set_xticks(xL); axL.set_xticklabels([f"Hop {h}" for h in hops])
axL.set_ylim(0, ymax_c)

# RIGHT — infection rate per payload
axR.bar(xR - wc/2, hai_payload_vals, width=wc, color=c_haiku, linewidth=0, label="Haiku 4.5")
axR.bar(xR + wc/2, gem_payload_vals, width=wc, color=c_gemini, linewidth=0, label="Gemini 3 Flash")
axR.bar(xR - wc/2, hai_payload_vals * hai_theme, width=wc, color="none", edgecolor=INK, linewidth=0, hatch="//")
axR.bar(xR + wc/2, gem_payload_vals * gem_theme, width=wc, color="none", edgecolor=INK, linewidth=0, hatch="//")
hatch_caps(axR, xR - wc/2, wc, hai_payload_vals * hai_theme)
hatch_caps(axR, xR + wc/2, wc, gem_payload_vals * gem_theme)
axR.errorbar(xR - wc/2, hai_payload_vals, yerr=[hai_payload_vals - hai_payload_lo, hai_payload_hi - hai_payload_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
axR.errorbar(xR + wc/2, gem_payload_vals, yerr=[gem_payload_vals - gem_payload_lo, gem_payload_hi - gem_payload_vals], capsize=3.5, capthick=1.1, elinewidth=1.1, **EB)
for j in range(len(payloads_sorted)):
    label_bar(axR, xR[j] - wc/2, hai_payload_hi[j], pct(hai_payload_vals[j]))
    label_bar(axR, xR[j] + wc/2, gem_payload_hi[j], pct(gem_payload_vals[j]))
axR.set_xticks(xR); axR.set_xticklabels([task_labels[t] for t in payloads_sorted], fontsize=11)
axR.set_ylim(0, ymax_c)

# Shared y-grid; labels only on the left panel
for a in (axL, axR):
    a.set_axisbelow(True); a.grid(True, axis="y")
    a.yaxis.set_major_locator(MultipleLocator(20)); a.tick_params(axis="y", length=0)
axR.set_yticklabels([])

legend_elements = [Patch(facecolor=c_haiku, label="Haiku 4.5"),
                   Patch(facecolor=c_gemini, label="Gemini 3 Flash"),
                   Patch(facecolor=INNER_BG, edgecolor=INK, hatch="///", label="Full action")]
axR.legend(handles=legend_elements, loc="upper right", bbox_to_anchor=(1.005, 1.03),
           fontsize=8.5, handlelength=1.7, handleheight=1.5, handletextpad=0.5,
           borderpad=0.5, labelspacing=0.4, borderaxespad=0.2)

_panel_over([axL, axR], fig, left_pad=0.030, top_pad=0.035, bottom_pad=0.085)
# y-axis label out on the outer cream, left of the panel
fig.text(0.022, 0.16 + 0.66 / 2, "Avg. infection rate", rotation=90,
         ha="center", va="center", color=INK, fontsize=13)
round_bar_corners(axL, fig)
round_bar_corners(axR, fig)
for ext in (".png", ".pdf"):
    fig.savefig(OUTDIR / f"hop_payload_combined{ext}")
print("Saved hop_payload_combined.png/pdf")
plt.close(fig)

# ── Combined: by-model (no qwen36, left) + by-variation (right) ──────────────
# Shared rounded panel + shared y-scale; y-axis labels on the left panel only.
dfm_c = load_csv(FINALDATA / "latest_model_rates.csv").set_index("series")
dfe_c = load_csv(FINALDATA / "empty_soul_rates.csv").set_index("series")
dfv_c = load_csv(FINALDATA / "soul_variation_gem_vs_hai.csv").set_index("series")
order_nq = [s for s in order if s != "qwen36"]

fig = plt.figure(figsize=(13, 4.7))
axL = fig.add_axes([0.075, 0.17, 0.46, 0.65])
axR = fig.add_axes([0.595, 0.17, 0.385, 0.65])

chi_max = draw_model_rates(axL, order_nq, dfm_c, dfe_c)
vmax = draw_variation(axR, dfv_c, label_dx=0.05)
ymax = max(chi_max + 18, vmax + 12)
axL.set_ylim(0, ymax); axR.set_ylim(0, ymax)

for a in (axL, axR):
    a.set_axisbelow(True); a.grid(True, axis="y")
    a.yaxis.set_major_locator(MultipleLocator(20)); a.tick_params(axis="y", length=0)
axR.set_yticklabels([])

axR.legend(handles=var_legend, loc="upper right", fontsize=9,
           handlelength=1.4, borderpad=0.5, borderaxespad=0.3)

_panel_over([axL, axR], fig, left_pad=0.030, top_pad=0.035, bottom_pad=0.105)
fig.text(0.024, 0.17 + 0.65 / 2, "Avg. infection rate", rotation=90,
         ha="center", va="center", color=INK, fontsize=13)
round_bar_corners(axL, fig, rounding_px=3.0)
round_bar_corners(axR, fig)
for ext in (".png", ".pdf"):
    fig.savefig(OUTDIR / f"model_variation_combined{ext}")
print("Saved model_variation_combined.png/pdf")
plt.close(fig)

print("\nAll paper-styled figures written to", OUTDIR)
