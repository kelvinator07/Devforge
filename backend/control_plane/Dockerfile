# DevForge control plane — Lambda container image.
# Build from the devforge/ repo root so we pull in `backend/common` + `backend/control_plane`:
#
#   docker build --platform linux/amd64 \
#     -f backend/control_plane/Dockerfile -t <ecr>/devforge-control-plane:<tag> .
#
# scripts/deploy_aws.sh handles the build context.
FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.12

RUN pip install --no-cache-dir uv

WORKDIR /var/task

COPY pyproject.toml ./
RUN uv sync --no-install-project --extra aws

# Vendor site-packages into Lambda's task root so imports work without PYTHONPATH gymnastics.
RUN cp -r .venv/lib/python3.12/site-packages/. /var/task/

COPY backend/ /var/task/backend/

ENV DEVFORGE_BACKEND=aws

CMD ["backend.control_plane.main.handler"]
