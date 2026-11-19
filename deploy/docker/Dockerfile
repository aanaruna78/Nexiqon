# One image for every deployment group; NEXIQON_GROUP selects which services run (deploy/groups.yaml).
FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.12.15-slim AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY libs libs
COPY services services
# Plain RUN (no BuildKit cache mount) so the image builds with any Docker builder; CI caches layers.
RUN uv sync --frozen --no-dev --all-packages --no-editable \
    && rm -rf /root/.cache/uv

FROM python:3.12.15-slim
# DV-01: a minimal runtime. Debian slim rather than distroless because the ingestion Git connector
# needs the git binary (HTTPS shallow clones, pinned to checked addresses). Hardening: current
# security updates; no pip, setuptools or wheel (the app's virtualenv has none either); no apt
# lists; no setuid/setgid programs; a non-root user; started without a shell. Kubernetes adds a
# read-only root filesystem and drops every capability (deploy/helm).
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /var/log/* \
    && python -m pip uninstall -y pip setuptools wheel \
    && rm -rf /usr/local/lib/python3.12/ensurepip \
    && find / -xdev -perm /6000 -type f -exec chmod a-s {} + \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin nexiqon
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY deploy/groups.yaml /app/deploy/groups.yaml
# Ready-made Domain Packs offered by config's pack gallery (ST-13).
COPY packs /app/packs
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    NEXIQON_GROUP=control-core
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
ENTRYPOINT ["nexiqon-run", "--groups-file", "/app/deploy/groups.yaml"]
