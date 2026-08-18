#!/bin/bash
set -euo pipefail
export DOT_DIR=$(dirname $(realpath $0))

echo "deploying on machine..."
echo "source $DOT_DIR/config/zshrc.sh" > $HOME/.zshrc
echo "source $DOT_DIR/config/tmux.conf" > $HOME/.tmux.conf
echo "Reload shell for changes to take effect!"
