FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    curl \
    git \
    jq \
    vim \
    zip \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace

WORKDIR /workspace

CMD ["/bin/bash"]
