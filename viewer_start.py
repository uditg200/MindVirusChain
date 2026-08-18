"""Render deployment entry point for the Virus Chain Viewer."""

import os
from pathlib import Path

import uvicorn

from virus_chain.viewer import app as viewer_module

# Use experiments directory bundled with the repo
ROOT = Path("experiments/virus_chain_runs")

if not ROOT.is_dir():
    print(f"Warning: Results directory not found at {ROOT}, viewer will show empty.")
    ROOT.mkdir(parents=True, exist_ok=True)

viewer_module.ROOT_DIR = ROOT.resolve()

# Discover campaigns on startup
campaigns = viewer_module._discover_campaigns()
print(f"Serving results from: {ROOT.resolve()}")
print(f"Discovered {len(campaigns)} campaigns")

if len(campaigns) == 1:
    viewer_module._set_campaign(campaigns[0]["name"])
    print(f"Auto-selected: {campaigns[0]['name']}")

# Render sets PORT env var
port = int(os.environ.get("PORT", 8779))

uvicorn.run(viewer_module.app, host="0.0.0.0", port=port)
