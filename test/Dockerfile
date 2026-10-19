# Test tooling is isolated from the shipping image.
ARG LOOPHOLE_IMAGE=playwright-loophole:test
FROM ${LOOPHOLE_IMAGE}
USER root
# WebSocket clients need matching major/minor versions. Python may not publish
# every Node patch release (e.g. Node 1.64.1 uses Python 1.64.0).
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/verification \
    && version="$(node -p 'require("playwright/package.json").version')" \
    && minor="${version%.*}" \
    && /opt/verification/bin/pip install --no-cache-dir "playwright==$minor.*" 'python-hosts==1.1.1'
COPY test/browser_check.py /opt/verification/browser_check.py
