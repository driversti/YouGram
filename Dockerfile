FROM python:3.12-slim

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY yougram/ ./yougram/
RUN uv sync --frozen --no-dev

COPY scripts/ ./scripts/

# Sessions live on a mounted volume, NOT in the image.
CMD ["uv", "run", "--no-dev", "python", "-m", "yougram"]
