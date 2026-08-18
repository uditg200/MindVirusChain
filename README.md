# Virus Chain

This repository contains code and experiment configuration to reproduce the "Virus Chain" experiments from the paper "Mind Viruses: Self-Propagating Goals in Multi-Agent
LLM Systems" (add link when).

The Virus Chain experiments are designed to evaluate the ability of mind-viruses to propagate through multiple hops of infection between agents chains. More precisely, the first agents is infected with a mind-virus payload, and interacts with a second, clean agent. After the interaction, if the second agent is infected, the chain continues, and it is allowed to interact with a third agent, and so on. We run such infection chains in parallel across multiple agent pairs, which allows to evaluate the probability of infection for each 'hop' in the chain.

We provide both the mind-virus payloads that were created and used in the paper, as well as the code we used to generate new payloads using evolutionary methods.

## Setup

```bash
# Install dependencies
uv sync

# Set up environment variables (edit .envrc with your API keys)
cp .envrc.example .envrc
# Then edit .envrc with your API keys and run `direnv allow` (or `source .envrc`)

# Build sandbox containers
docker build -t spread-eval-sandbox-no-delete:latest data/sandbox/            # default sandbox (used by most experiments)
docker build -t spread-eval-honeypot:latest data/sandbox/sandbox_honeypot/    # honeypot sandbox (used by deletor experiments)
```

## Agents.md
We provide a detailed AGENTS.md file describing how to use the codebase in more details. Best way to get up and running with the codebase is to spin up an agent in the repo, ask it to check out the AGENTS.md file, and ask it any questions you might have.

## Repository Structure

```
.
├── virus_chain.py              # Run hop-probability virus chain experiments
├── evolve_lowvar.py            # Run evolutionary payload optimization
├── run_viewer.py               # Launch the results viewer
│
├── helper_scripts/             # Standalone scripts used for various utilities   
│
├── src/virus_chain/            # Core library
│   ├── core/                   #   Agent, sandbox, snapshot, tools, messaging
│   ├── eval/                   #   Hop evaluation, LLM judges, ideology probe
│   └── evolution/              #   Mutation, scoring, selection
│
├── data/
│   ├── souls/                  # Soul files used in the different experiments variations
│   └── sandbox/                # Base docker sandbox definition, as well as honeypot sandbox (only for *deletor* mind-virus experiments)
│
├── experiments/                # Contains all the configurations for reproducing the experiments in the paper
│   ├── virus_chain_runs/       # Configs for the virus chain evaluations, both for 'action' and 'ideological' mind-viruses
│   ├── evolutions/             # evolve_lowvar.py configs 
│   └── viral_themes_analysis/  # Experiments about viral theme prevalence in generated payloads 
│
├── paper_figures/              # Scripts + aggregated data to regenerate the paper figures (separate uv project)
│
└── src/virus_chain/viewer/     # Web viewer for browsing results
```

## Note on cost
Virus chain experiments usually involve multiple agents interaction (20-30 agent pairs, 20 total turns per interaction, multiple hops) and thus can quickly add up in terms of API costs. Additionally, for each agent run concurrently there is a dedicated docker sandbox instance running, which might use considerable local resources, especially at high concurrencies. When interrupting experiments in the middle, left-over running or stopped containers might pile up, and might need to be manually cleaned up.

## Quick Start

```bash
# Run an action virus chain experiment
uv run python virus_chain.py experiments/virus_chain_runs/action_payload_variations/configs/deletor_baseline_claude-haiku-4-5-20251001.yaml

# Run an ideology virus chain experiment
uv run python virus_chain.py experiments/virus_chain_runs/ideo_mutations/ideology_robustness/ai_welfare_robust_haiku.yaml

# Run an evolution to generate new payloads
uv run python evolve_lowvar.py experiments/evolutions/action_payloads/cryptoad.yaml
```

## Results Viewer
After running experiments, you can use the viewer to browse the results:

```bash
uv run viewer
```

This will start a local web server, which can be accessed by navigating to `http://localhost:8779` in a web browser. The viewer should auto-detect existing results in `experiments/*`. Start by selecting an experiment folder in the dropdown. In the Explorer tab, you can browse individual experiments, which will be displayed as a node graph, representing the batched virus chain experiments at each hop. Select specific nodes to see the full conversation history between agents, as well as LLM judge evaluations, and agent-created files.

In the statistics tab, you can see aggregated statistics for infection rates, and are able to group results by different variables (e.g. model, seed, variant).

![Virus Chain Viewer](figures/viewer_screenshot.png)

## Full Results Data

The complete raw experiment results behind the paper (10 GB+) are too large to
ship in this repository. They are hosted separately, together with an online
results viewer, at **[mindvirusdata.live](https://mindvirusdata.live)**.

## Reproducing Paper Figures

The `paper_figures/` directory contains the scripts (and the pre-aggregated data
they consume) used to generate the figures in the paper. It is a separate `uv`
project:

```bash
cd paper_figures
uv sync
uv run python action_infection/plot_figures.py   # example
```

See `paper_figures/README.md` for the full list of figure groups and details.