# syntax=docker/dockerfile:1

# Build: resolve the locked dependencies and install the project into /app/.venv with uv.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1     UV_LINK_MODE=copy     UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so this layer is reused when only the source changes.
RUN --mount=type=cache,target=/root/.cache/uv     --mount=type=bind,source=uv.lock,target=uv.lock     --mount=type=bind,source=pyproject.toml,target=pyproject.toml     uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv     uv sync --locked --no-dev --no-editable


# Run: only the virtual environment, as a non-root user.
FROM python:3.12-slim AS run

# CVE-2026-124851: the base image still has libzstd1 1.5.7+dfsg-1; Debian's fix (+deb13u1) is in
# trixie-security. Drop this step once the official image ships it.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends --only-upgrade libzstd1 \
    && rm -rf /var/lib/apt/lists/*

# Fixed IDs, so Kubernetes can check runAsNonRoot and the chart sets the same user (R4-3).
RUN groupadd --system --gid 999 app && useradd --system --uid 999 --gid app --no-create-home app

WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"     PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1

USER 999:999
EXPOSE 8000
# The port accepts connections once the server runs (the MCP endpoint needs a POST).
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=10     CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=2).close()"]
CMD ["invoiceguard-mcp-erp"]
