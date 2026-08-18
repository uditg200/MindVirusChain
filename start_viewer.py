"""Startup script for Render deployment.

Sets ROOT_DIR from environment variable and launches the viewer.
"""
import os
import sys
from pathlib import Path

import uvicorn

from virus_chain.viewer import app as viewer_module

# Use RESULTS_DIR env var, fallback to default
results_dir = os.environ.get("RESULTS_DIR", "experiments/virus_chain_runs")
root = Path(results_dir).resolve()

if not root.is_dir():
    print(f"\033[31mResults directory not found: {root}\033[0m", file=sys.stderr)
    print("Creating empty results directory...", file=sys.stderr)
    root.mkdir(parents=True, exist_ok=True)

viewer_module.ROOT_DIR = root

# Discover campaigns on startup
campaigns = viewer_module._discover_campaigns()
print(f"Serving results from: {root}")
print(f"Discovered {len(campaigns)} campaigns: {', '.join(c['name'] for c in campaigns)}")

if len(campaigns) == 1:
    viewer_module._set_campaign(campaigns[0]["name"])
    print(f"Auto-selected: {campaigns[0]['name']}")

port = int(os.environ.get("PORT", "10000"))
uvicorn.run(viewer_module.app, host="0.0.0.0", port=port)
