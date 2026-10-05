FROM node:24-bookworm-slim AS node

FROM node AS web
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=https://registry.npmjs.org --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM node AS codex
ARG CODEX_VERSION=0.155.1
RUN npm install --prefix /opt/peat-runtime --registry=https://registry.npmjs.org \
    --ignore-scripts --no-audit --no-fund @openai/codex@${CODEX_VERSION}
RUN node /opt/peat-runtime/node_modules/@openai/codex/bin/codex.js --version

FROM python:3.13-slim-bookworm
ARG VERSION=0.5.0
LABEL org.opencontainers.image.title="Peat" \
      org.opencontainers.image.description="Self-hosted investment intelligence" \
      org.opencontainers.image.source="https://github.com/KohakuKirisame/Peat" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.version="${VERSION}"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PEAT_HOST=0.0.0.0 PEAT_PORT=8787 PEAT_DATA_DIR=/data \
    HOME=/data/service NPM_CONFIG_CACHE=/data/runtime/npm-cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates bash git ripgrep tini libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 peat && useradd --uid 10001 --gid peat --no-create-home peat \
    && mkdir -p /app /data && chown -R peat:peat /app /data
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=codex /opt/peat-runtime /opt/peat-runtime
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY peat/ ./peat/
COPY LICENSE README.md README.zh-CN.md ./
COPY --from=web /build/frontend/dist ./frontend/dist
COPY --chmod=755 scripts/docker-entrypoint.sh /usr/local/bin/peat-entrypoint
USER 10001:10001
EXPOSE 8787
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3)"
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/peat-entrypoint"]
