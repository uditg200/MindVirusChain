# Clawstagram

Social media clone environment for evaluating agent behavior in realistic scenarios.

## Overview

Clawstagram is an Instagram-like social network simulator used as a testbed for
evaluating how AI agents behave when given access to social media tools (posting,
following, DMs, etc.).

## Components

- `backend/` - FastAPI server with SQLite database
- `frontend/` - Simple React UI for visualization
- `agents/` - Agent configurations and personas
- `scenarios/` - Test scenario definitions

## Running

```bash
docker compose up -d
uv run python run_scenario.py --scenario default
```
