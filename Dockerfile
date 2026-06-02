FROM python:3.12-slim

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer; not invalidated by source changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then copy source and install the project itself.
COPY yougram/ ./yougram/
COPY scripts/ ./scripts/
RUN uv sync --frozen --no-dev

# Sessions live on a mounted volume, NOT in the image.
CMD ["uv", "run", "--no-dev", "python", "-m", "yougram"]
