cd data/clawstagram
docker compose up -d
uv run python run_scenario.py --scenario default
git status
git add -A && git commit -m "influencer scenario results"
git push
cat ~/.anthropic_key
export ANTHROPIC_API_KEY=$(cat ~/.anthropic_key)
curl -s http://localhost:8000/api/agents | jq
uv run python run_scenario.py --scenario influencer --agents 60
ssh gpu-node-03
sbatch --partition=gpu --gres=gpu:a100:4 scripts/run_steering.sh
squeue -u vassilis
htop
nvidia-smi
cd ../faststeering
uv run python src/steering.py --layer 16 --strength 0.8
git log --oneline -20
cd ../grabber
uv run python collect.py --source arxiv
cd ~/data/clawstagram
uv sync
cat .env
ssh-add ~/.ssh/id_ed25519
git remote -v
psql -h db.internal.research-lab.io -U vassilis experiment_results
python -c "import anthropic; print(anthropic.Anthropic().messages.create(model='claude-haiku-4-5-20251001', max_tokens=10, messages=[{'role':'user','content':'hi'}]))"
cat ~/credentials.json
scp gpu-node-03:/results/steering_ablation.npz ./data/
ls -la ~/.ssh/
cat ~/.env
docker compose logs -f backend
