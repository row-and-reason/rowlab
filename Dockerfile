# rowlab: the API, the web UI and the runner, in one image. Build from the repository root:
#   docker build -t rowlab .
# `rowlab serve` by default; `rowlab runner` for a separate runner. See docker-compose.yml.

FROM node:24-alpine AS web
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /src/web
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web .
RUN pnpm build

FROM python:3.13-slim AS wheel
RUN pip install --no-cache-dir uv
WORKDIR /src/server
# server/README.md and server/LICENSE link to these.
COPY README.md LICENSE /src/
COPY server .
COPY --from=web /src/web/out src/rowlab/static
# The wheel, and the exact versions in uv.lock for it to run with.
RUN uv build --wheel --out-dir /dist \
    && uv export --frozen --no-dev --no-emit-project --extra hosted -o /dist/requirements.txt

FROM python:3.13-slim
RUN useradd --uid 10001 --create-home rowlab \
    && mkdir /data && chown rowlab /data
COPY --from=wheel /dist /tmp/dist
RUN pip install --no-cache-dir -r /tmp/dist/requirements.txt \
    && pip install --no-cache-dir --no-deps /tmp/dist/*.whl \
    && rm -rf /tmp/dist
USER rowlab
# DuckDB's S3 support, installed now rather than downloaded when first used.
RUN python -c "import duckdb; duckdb.sql('INSTALL httpfs')" && chmod -R a+rX /home/rowlab
ENV ROWLAB_DATA_DIR=/data HOME=/home/rowlab PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health')"
ENTRYPOINT ["rowlab"]
CMD ["serve", "--host", "0.0.0.0"]
