FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv git ca-certificates \
    && npm install -g @github/copilot \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/work

