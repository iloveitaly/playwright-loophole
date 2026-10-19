# syntax=docker/dockerfile:1
ARG PLAYWRIGHT_VERSION=v1.50.0-noble
FROM mcr.microsoft.com/playwright:${PLAYWRIGHT_VERSION}
ARG PLAYWRIGHT_VERSION
LABEL org.opencontainers.image.title="playwright-loophole" \
      org.opencontainers.image.description="Playwright with a transparent localhost TCP relay to the host"
RUN apt-get update && apt-get install -y --no-install-recommends \
      haproxy tini libcap2-bin libnss3-tools iproute2 \
    && rm -rf /var/lib/apt/lists/* \
    && setcap 'cap_net_bind_service=+ep' /usr/sbin/haproxy
# The upstream image contains browser binaries, but no npm driver.
RUN version="${PLAYWRIGHT_VERSION#v}" && version="${version%-*}" \
    && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --global "playwright@$version" "@playwright/test@$version" \
    && npm cache clean --force
ENV NODE_PATH=/usr/lib/node_modules:/usr/local/lib/node_modules
RUN mkdir -p /etc/chromium/policies/managed /etc/opt/chrome/policies/managed /etc/opt/chrome_for_testing/policies/managed \
    && printf '{"QuicAllowed":false}\n' | tee \
      /etc/chromium/policies/managed/loophole-disable-quic.json \
      /etc/opt/chrome/policies/managed/loophole-disable-quic.json \
      /etc/opt/chrome_for_testing/policies/managed/loophole-disable-quic.json >/dev/null
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PLAYWRIGHT_PORT=3000
EXPOSE 3000
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["sh", "-c", "exec playwright run-server --port \"${PLAYWRIGHT_PORT}\" --host 0.0.0.0"]
