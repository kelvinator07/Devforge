# DevForge worker — ECS Fargate task image.
# Derived from alex/backend/researcher/Dockerfile; swaps litellm/Bedrock wiring
# for the OpenAI-compatible client pointed at OpenRouter.
FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app

# System packages: git + gh CLI + curl for node installer.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
 && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get update && apt-get install -y --no-install-recommends nodejs gh \
 && rm -rf /var/lib/apt/lists/*

# Python package manager
RUN pip install --no-cache-dir uv

# Install Python deps ahead of source copy so dependency changes don't blow the cache.
COPY pyproject.toml ./
RUN uv sync --no-install-project

# Application code
COPY *.py *.yaml ./

# Default entrypoint runs the Day-2 smoke test. Override via DEVFORGE_WORKER_MODE.
CMD ["uv", "run", "python", "crew.py"]
