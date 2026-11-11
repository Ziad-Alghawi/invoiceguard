# syntax=docker/dockerfile:1

# Build: resolve the locked dependencies and install the project into /app/.venv with uv.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so this layer is reused when only the source changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


# Run: the virtual environment and the migrations, as a non-root user.
FROM python:3.12-slim AS run

# A named volume mounted on /data/uploads takes over this owner, so the app user can write uploads.
RUN groupadd --system app && useradd --system --gid app --no-create-home app \
    && mkdir -p /data/uploads && chown app:app /data/uploads

WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INVOICEGUARD_STORAGE_DIR=/data/uploads

USER app
EXPOSE 8000
CMD ["uvicorn", "--factory", "invoiceguard_api.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
