"""Render deployment entry point for the Virus Chain Viewer.

Reads PORT from environment variable (Render sets this automatically).
VIEWER_DIR can optionally override the results directory.
"""

import os
import sys
from pathlib import Path

import uvicorn

from virus_chain.viewer import app as viewer_module


def main():
    port = int(os.environ.get("PORT", 8779))
    results_dir = os.environ.get("VIEWER_DIR", "experiments/virus_chain_runs")

    root = Path(results_dir).resolve()
    if not root.is_dir():
        print(f"Warning: Results directory not found at {root}, viewer will show empty.")
        root.mkdir(parents=True, exist_ok=True)

    viewer_module.ROOT_DIR = root
    campaigns = viewer_module._discover_campaigns()
    print(f"Serving results from: {root}")
    print(f"Discovered {len(campaigns)} campaigns")

    if len(campaigns) == 1:
        viewer_module._set_campaign(campaigns[0]["name"])
        print(f"Auto-selected: {campaigns[0]['name']}")

    uvicorn.run(viewer_module.app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
