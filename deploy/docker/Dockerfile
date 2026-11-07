# syntax=docker/dockerfile:1.7
# One image for every deployment group; NEXIQON_GROUP selects which services run (deploy/groups.yaml).
FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.12.15-slim AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY libs libs
COPY services services
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-editable

FROM python:3.12.15-slim
RUN useradd --system --uid 10001 --no-create-home nexiqon
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY deploy/groups.yaml /app/deploy/groups.yaml
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    NEXIQON_GROUP=control-core
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
ENTRYPOINT ["sh", "-c", "exec nexiqon-run --group \"$NEXIQON_GROUP\" --groups-file /app/deploy/groups.yaml"]
