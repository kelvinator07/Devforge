FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.12

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /var/task

COPY pyproject.toml ./
RUN uv sync --no-install-project
# Copy vendored site-packages to Lambda task root so Mangum/FastAPI import cleanly
RUN cp -r .venv/lib/python3.12/site-packages/. /var/task/

COPY *.py /var/task/

CMD ["main.handler"]
