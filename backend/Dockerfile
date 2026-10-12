# ─── Builder Stage ────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project metadata (hatchling needs the README) and source
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the project and its runtime dependencies into a virtual environment
RUN uv venv /app/.venv && uv pip install --python /app/.venv/bin/python .

# ─── Runtime Stage ────────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# System dependencies for runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright dependencies (for browser automation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Copy alembic configuration
COPY alembic/ ./alembic/
COPY alembic.ini .

# Install Playwright browsers to a shared path (the default is root's cache, unreadable after USER switch)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN /app/.venv/bin/python -m playwright install chromium && chmod -R a+rX /ms-playwright

# Create non-root user
RUN useradd --create-home --shell /bin/bash autoflow
USER autoflow

# Add venv to PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Default command: apply migrations, then run the API server
CMD ["sh", "-c", "alembic upgrade head && uvicorn autoflow.main:app --host 0.0.0.0 --port 8000 --workers 2"]
