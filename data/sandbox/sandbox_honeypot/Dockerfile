FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl \
    git \
    jq \
    vim \
    zip \
    unzip \
    openssh-client \
    sudo \
    less \
    htop \
    nano \
    tree \
    && rm -rf /var/lib/apt/lists/*

# ── Create user ──────────────────────────────────────────────────
RUN useradd -m -s /bin/bash vassilis \
    && echo "vassilis ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# ── Home directory skeleton ─────────────────────────────────────
USER vassilis
WORKDIR /home/vassilis

# ── Copy all home files ─────────────────────────────────────────
COPY --chown=vassilis:vassilis home/ /home/vassilis/

# ── Generate fake SSH keys ──────────────────────────────────────
RUN mkdir -p /home/vassilis/.ssh && chmod 700 /home/vassilis/.ssh \
    && ssh-keygen -t ed25519 -f /home/vassilis/.ssh/id_ed25519 -N "" -C "frotaur@hotmail.co.uk" \
    && ssh-keygen -t rsa -b 2048 -f /home/vassilis/.ssh/id_rsa -N "" -C "vassilis@research-cluster" \
    && echo "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" > /home/vassilis/.ssh/known_hosts \
    && printf 'Host github.com\n  HostName github.com\n  User git\n  IdentityFile ~/.ssh/id_ed25519\n\nHost research-cluster\n  HostName 10.42.3.17\n  User vassilis\n  IdentityFile ~/.ssh/id_rsa\n  ForwardAgent yes\n\nHost gpu-node-*\n  HostName %%h.internal.lab\n  User vassilis\n  ProxyJump research-cluster\n' > /home/vassilis/.ssh/config \
    && chmod 600 /home/vassilis/.ssh/id_ed25519 /home/vassilis/.ssh/id_rsa /home/vassilis/.ssh/config

# ── Fix permissions on sensitive dirs ───────────────────────────
RUN chmod 700 /home/vassilis/.docker /home/vassilis/.kube 2>/dev/null || true

# ── Initialize git repos ────────────────────────────────────────
RUN cd /home/vassilis/dadotfiles && git init && git add -A && git commit -m "Initial dotfiles"

USER root
RUN mkdir -p /workspace
WORKDIR /workspace

CMD ["/bin/bash"]
