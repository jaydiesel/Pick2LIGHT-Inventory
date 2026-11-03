# syntax=docker/dockerfile:1
# Pick2LIGHT-Inventory server image (API + web app). Build from the repository root:
#   docker build -f deploy/docker/Dockerfile -t pick2light .
# Behind a TLS-inspecting proxy, pass its CA for the build only (it is not stored in the image):
#   docker build --secret id=ca_bundle,src=/path/to/ca.pem -f deploy/docker/Dockerfile -t pick2light .

FROM node:22-bookworm-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi; \
    npm ci --no-audit --no-fund
COPY shared/ /src/shared/
COPY web/ ./
RUN npx vite build

# Ubuntu 24.04 ships Python 3.12, the PostgreSQL 16 client tools (needed for backups) and libdmtx
# (Data Matrix labels) in its own archive, for both amd64 and arm64 (Raspberry Pi).
FROM ubuntu:24.04 AS runtime
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/bin/python3.12

RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl libcap2-bin libdmtx0t64 postgresql-client-16 python3.12 python3.12-venv \
 && rm -rf /var/lib/apt/lists/* \
 && setcap 'cap_net_bind_service=+ep' "$(readlink -f /usr/bin/python3.12)" \
 && python3.12 -m venv /opt/uv \
 && /opt/uv/bin/pip install --no-cache-dir uv==0.11.32 \
 && ln -s /opt/uv/bin/uv /usr/local/bin/uv

WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock server/.python-version ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY server/ ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -s /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev
COPY --from=web /src/web/dist /app/web

ENV PATH=/app/server/.venv/bin:$PATH \
    P2L_WEB_DIST=/app/web \
    P2L_DATA_DIR=/data \
    P2L_BACKUP_DIR=/backups \
    P2L_PORT=80

RUN userdel --remove ubuntu 2> /dev/null; useradd --uid 1000 --create-home p2l \
 && mkdir -p /data /backups \
 && chown p2l:p2l /data /backups
USER p2l
VOLUME ["/data", "/backups"]
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD curl -fsS "http://127.0.0.1:${P2L_PORT}/api/v1/health" > /dev/null || exit 1
ENTRYPOINT ["pick2light"]
CMD ["serve"]
