# Test tooling is isolated from the shipping image.
ARG LOOPHOLE_IMAGE=playwright-loophole:test
FROM ${LOOPHOLE_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/verification \
    && version="$(node -p 'require("playwright/package.json").version')" \
    && /opt/verification/bin/pip install --no-cache-dir "playwright==$version" 'python-hosts==1.1.1'
COPY test/browser_check.py /opt/verification/browser_check.py
