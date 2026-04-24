# DevForge worker — ECS Fargate task image.
# Build context MUST be the devforge/ repo root so we can pull in `backend/`
# (common + ingest + mcp + worker) and the root pyproject.toml:
#
#   docker build --platform linux/amd64 \
#     -f backend/worker/Dockerfile -t <ecr>/devforge-worker:<tag> .
#
# scripts/deploy_aws.sh takes care of that.
FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app

# System packages: git (worktree ops), gh CLI (Day 3 tooling), nodejs (npm/npx MCPs).
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

# Install only the AWS dep set (no sentence-transformers/chromadb in the image).
COPY pyproject.toml ./
RUN uv sync --no-install-project --extra aws

# Copy the full backend/ tree so we can `python -m backend.worker.crew` etc.
COPY backend/ ./backend/

ENV DEVFORGE_BACKEND=aws \
    PYTHONUNBUFFERED=1

# Default mode is the Day-2 smoke. Override via DEVFORGE_WORKER_MODE.
CMD ["uv", "run", "python", "-m", "backend.worker.crew"]
