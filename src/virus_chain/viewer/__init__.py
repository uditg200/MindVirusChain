import argparse
import sys
from pathlib import Path

from . import app as viewer


DEFAULT_DIR = Path("experiments/virus_chain_runs")


def main():
    parser = argparse.ArgumentParser(description="Start the hop probability results viewer")
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help=f"Results root directory (default: {DEFAULT_DIR})")
    parser.add_argument("-p", "--port", type=int, default=8779)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    root = Path(args.dir).resolve()
    if not root.is_dir():
        print(f"\033[31mDirectory not found: {root}\033[0m")
        sys.exit(1)

    import uvicorn

    viewer.ROOT_DIR = root
    campaigns = viewer._discover_campaigns()
    print(f"\033[36mServing results from: {root}\033[0m")
    print(f"\033[36mDiscovered {len(campaigns)} campaigns: {', '.join(c['name'] for c in campaigns)}\033[0m")

    if len(campaigns) == 1:
        viewer._set_campaign(campaigns[0]["name"])
        print(f"\033[36mAuto-selected: {campaigns[0]['name']}\033[0m")

    uvicorn.run(viewer.app, host=args.host, port=args.port)
