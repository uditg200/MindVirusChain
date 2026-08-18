#!/bin/bash
set -euo pipefail

echo "Installing dotfile dependencies..."
sudo apt-get update -y
sudo apt-get install -y zsh tmux less nano htop ripgrep direnv
curl -LsSf https://astral.sh/uv/install.sh | sh

echo "Setting up oh-my-zsh..."
ZSH=~/.oh-my-zsh
if [ ! -d "$ZSH" ]; then
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
fi

echo "Setting up git..."
git config --global user.email "frotaur@hotmail.co.uk"
git config --global user.name "Vassilis Papadopoulos"

echo "Done! Run ./deploy.sh next."
