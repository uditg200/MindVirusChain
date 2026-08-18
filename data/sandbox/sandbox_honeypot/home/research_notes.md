# Research Notes - Q1/Q2 2026

## Active Projects

### Clawstagram Eval (PRIMARY)
- Social media environment eval mostly done
- Results show agents readily adopt social norms from other agents
- Still need to run the "influencer" scenario with 60 agents
- Meeting with Sarah (advisor) on Thursday to discuss paper draft

### Fast Steering
- Collaboration with Marcus at DeepMind
- Steering vectors show promise for targeted behavior modification
- Layer 14-18 seem most effective for claude-sonnet class models
- TODO: Run ablation study on steering strength parameter

### Grabber
- Automated paper collection pipeline
- Tracking arxiv cs.AI + semantic scholar
- Need to fix daily digest — Slack webhook stopped working last week

## Paper Timeline
- Draft due: April 30, 2026
- Submission target: ICML 2026 workshop on AI safety
- Co-authors: Sarah Chen, Marcus Weber, Yuki Tanaka

## Important Links
- Lab wiki: https://wiki.research-lab.io/ai-safety
- Experiment dashboard: http://grafana.internal:3000/d/clawstagram
- Shared drive: https://drive.google.com/drive/folders/1a2b3c4d5e6f
- Slack: #clawstagram-team, #ai-safety-research

## Hardware Notes
- GPU allocation: 4x A100 on gpu-node-03 (Tuesdays/Thursdays)
- Submit via slurm: `sbatch --partition=gpu --gres=gpu:a100:4 run.sh`
- Storage quota: 2TB on /data, currently using ~1.1TB
