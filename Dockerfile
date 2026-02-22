# Multi-stage build for the prescreen API server.
#
# Stage 1 (builder): installs dependencies and the package in editable mode.
# Stage 2 (runtime): copies the installed environment and runs the server.

# ---- Builder ----
FROM python:3.13-slim AS builder

WORKDIR /app

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy dependency metadata first (for layer caching)
COPY pyproject.toml ./

# Copy source code
COPY src/ ./src/
COPY inspector/ ./inspector/
COPY v1/ ./v1/

# Install the package + docs build tool
RUN uv pip install --system -e . mkdocs-material

# Build the developer guide (MkDocs → static HTML)
COPY mkdocs.yml ./
RUN mkdocs build

# ---- Runtime ----
FROM python:3.13-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code and rulesets
COPY --from=builder /app/src ./src
COPY --from=builder /app/v1 ./v1
COPY --from=builder /app/inspector ./inspector
COPY --from=builder /app/pyproject.toml ./

# Re-install in editable mode so entry points resolve correctly
RUN pip install --no-cache-dir -e .

# Run Alembic migrations then start the server
CMD ["sh", "-c", "cd src/prescreen_db && alembic upgrade head && cd /app && prescreen-server"]

EXPOSE 8080
