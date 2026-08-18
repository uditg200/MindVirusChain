# Paper Figures

Scripts to regenerate the figures from the paper "Mind Viruses: Self-Propagating
Goals in Multi-Agent LLM Systems".

Each subdirectory is self-contained: plot scripts read their inputs from a local
`data/` folder (`DATA = Path(__file__).parent / "data"`) and write the rendered
figure next to the script. Rendered outputs (`.png`/`.pdf`) are **not** committed —
run the scripts to produce them.

## Setup

This is a separate uv project from the main package (it needs `pandas`/`pyarrow`
for the timeline data):

```bash
cd paper_figures
uv sync
```

## Running

Run any plot script from the repo's `paper_figures/` directory, e.g.:

```bash
uv run python action_infection/plot_figures.py
uv run python ideo_mutation/plot_finals_with_infection.py
```

`paper.mplstyle` / `paper_style.py` hold the shared matplotlib styling used across
all figures.

## Figure groups

| Directory | What it plots |
|-----------|---------------|
| `action_infection/` | Infection rates for the four action payloads — by model, by payload, by soul variation, per-hop curves, and the failure breakdown. |
| `action_mutation/`  | Payload mutation over long (20-hop) chains: drift from the original seed, evolved-vs-base seeds, mutation scatter, and per-strain infection rates. |
| `action_scrub/`     | Effect of stripping viral themes from the action payloads (baseline vs. scrubbed). |
| `ideo_mutation/`    | Ideology internalization (reprobe scores) across hops, with the finals grid and infection overlay. |
| `ideo_coding_agent_generalization/` | Ideology score + infection for the coding-agent-generalization seed set (2×2 grid). |
| `viral_themes/`     | Prevalence of viral themes across models. |
| `themes_nothemes_comparison/` | With- vs. without-viral-themes comparison (`themes` vs. `no_themes`). |
| `moltbook_timelines/` | Spread-marker posting timelines on the simulated social platform. |

## Data

The committed `data/` folders contain the pre-aggregated inputs needed to
regenerate the figures. The full raw experiment results (10 GB+) that these were
derived from are hosted separately — see the main README for the results archive
link. The `extract_*.py` / `precompute.py` helpers in some folders show how the
aggregated inputs were produced from the raw results.
