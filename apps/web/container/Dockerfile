FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY apps/web/requirements.lock /app/requirements.lock
RUN python -m pip install --require-hashes --only-binary=:all: -r requirements.lock

COPY pyproject.toml LICENSE /app/
COPY docs/pnbp.md /app/docs/pnbp.md
COPY src /app/src
RUN python -m pip install --no-deps --no-build-isolation . && python -m pip check

COPY apps/web/api /app/web/api
COPY apps/web/views /app/web/views
COPY apps/web/templates/shared /app/web/templates/shared
COPY apps/web/templates/home /app/web/templates/home
COPY apps/web/static /app/web/static
COPY apps/web/main.py apps/web/assets.py apps/web/web_config.py apps/web/install_assets.py apps/web/web-settings.json /app/web/
COPY apps/web/container/start.py apps/web/container/healthcheck.py /app/web/container/
RUN cd /app/web && python install_assets.py --check

ARG PNBP_REVISION
RUN python -c 'import os,re; revision=os.environ["PNBP_REVISION"]; assert re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision); open("/app/revision", "w").write(revision+"\n")'
LABEL org.opencontainers.image.source="https://github.com/outside-labs/pretty-notebook" \
      org.opencontainers.image.revision=$PNBP_REVISION

RUN groupadd --gid 10001 notebook && useradd --uid 10001 --gid 10001 --no-create-home notebook \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/pretty-notebook
USER 10001:10001
WORKDIR /app/web
ENV PNBP_DATA_DIR=/var/lib/pretty-notebook PNBP_ASSET_MODE=local PNBP_PORT=8000 PNBP_WORKERS=4
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 CMD ["python", "/app/web/container/healthcheck.py"]
ENTRYPOINT ["python", "/app/web/container/start.py"]
