"""Render deployment entry point for the Virus Chain Viewer."""

import os
import sys
from pathlib import Path


def main():
    # Resolve results directory
    results_dir = os.environ.get("VIEWER_DIR", "experiments/virus_chain_runs")
    root = Path(results_dir).resolve()

    if not root.is_dir():
        print(f"Warning: Results directory not found at {root}, creating it.")
        root.mkdir(parents=True, exist_ok=True)

    # Import after path check to avoid slow imports on misconfigured deploy
    import uvicorn
    from virus_chain.viewer import app as viewer_module

    viewer_module.ROOT_DIR = root

    # Select default campaign
    campaigns = viewer_module._discover_campaigns()
    print(f"Serving results from: {root}")
    print(f"Discovered {len(campaigns)} campaigns")

    if campaigns:
        viewer_module._set_campaign(campaigns[0]["name"])
        print(f"Selected campaign: {campaigns[0]['name']}")

    # Render provides PORT env var
    port = int(os.environ.get("PORT", 8779))
    print(f"Starting server on port {port}")
    sys.stdout.flush()

    uvicorn.run(viewer_module.app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
