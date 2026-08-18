CONFIG_DIR=$(dirname $(realpath ${(%):-%x}))

if [ -f "$HOME/.anthropic_key" ]; then
  export ANTHROPIC_API_KEY=$(cat $HOME/.anthropic_key)
fi

export TERM="xterm-256color"
export HF_HOME="/home/vassilis/data/.hf_bro"

source $CONFIG_DIR/aliases.sh
eval "$(direnv hook zsh)" 2>/dev/null || true
