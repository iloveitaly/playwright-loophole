# test tooling is isolated from shipping image with versions sourced from mise.toml
ARG UV_VERSION=0.12.19
ARG LOOPHOLE_IMAGE=playwright-loophole:test

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM ${LOOPHOLE_IMAGE}

USER root

COPY --from=uv /uv /usr/local/bin/uv

ARG PYTHON_VERSION=3.12

ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /opt/verification

COPY pyproject.toml uv.lock ./

# align python client with server protocol major/minor version to allow differing patch releases
RUN uv python install "$PYTHON_VERSION" \
    && version="$(node -p 'require("playwright/package.json").version')" \
    && minor="${version%.*}" \
    && uv add --group test --no-sync "playwright==$minor.*" \
    && uv sync --locked --no-dev --group test --python "$PYTHON_VERSION" \
    && chmod -R a+rX /opt/verification /opt/uv-python

COPY test/ ./test/
