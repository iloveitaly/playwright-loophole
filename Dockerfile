# syntax=docker/dockerfile:1

ARG PLAYWRIGHT_VERSION=v1.50.0-noble

FROM mcr.microsoft.com/playwright:${PLAYWRIGHT_VERSION}

ARG PLAYWRIGHT_VERSION
ARG TARGETARCH

LABEL org.opencontainers.image.title="playwright-loophole" \
      org.opencontainers.image.description="Playwright with a transparent localhost TCP relay to the host"

# allow haproxy to bind privileged ports when running as unprivileged pwuser
RUN apt-get update && apt-get install -y --no-install-recommends \
      haproxy tini libcap2-bin libnss3-tools iproute2 sudo curl ca-certificates python3 python3-yaml python3-click \
    && rm -rf /var/lib/apt/lists/* \
    && setcap 'cap_net_bind_service=+ep' /usr/sbin/haproxy

# temporary fork download/checksum workaround for the Caddy, JSON CLI, and direct-upstream improvements
# TODO: switch to a pinned upstream release once all improvements are merged into master/main and released
# TARGETARCH selects the matching binary; revisit the fork-specific downloads and checksums at that point
RUN case "$TARGETARCH" in \
      amd64) checksum=67ad8e63df718f91e72a890881aba79dbd54f8e5d4c8cdf364a8f344953cfd95 ;; \
      arm64) checksum=fa055ccaee487e5875865c96d1bb52d4c66bbe521b76258c2aa1db5ad49b2f37 ;; \
      *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/iloveitaly/localias/releases/download/v3.1.0/localias-linux-$TARGETARCH" -o /usr/local/bin/localias \
    && echo "$checksum  /usr/local/bin/localias" | sha256sum --check \
    && chmod 755 /usr/local/bin/localias

# upstream image contains browser binaries, but no npm driver
RUN version="${PLAYWRIGHT_VERSION#v}" && version="${version%-*}" \
    && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install --global "playwright@$version" "@playwright/test@$version" \
    && npm cache clean --force

ENV NODE_PATH=/usr/lib/node_modules:/usr/local/lib/node_modules

# disable quic so http/3 udp traffic cannot bypass the tcp relay
RUN mkdir -p /etc/chromium/policies/managed /etc/opt/chrome/policies/managed /etc/opt/chrome_for_testing/policies/managed \
    && printf '{"QuicAllowed":false}\n' | tee \
      /etc/chromium/policies/managed/loophole-disable-quic.json \
      /etc/opt/chrome/policies/managed/loophole-disable-quic.json \
      /etc/opt/chrome_for_testing/policies/managed/loophole-disable-quic.json >/dev/null

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --chmod=755 trust-ca.sh /usr/local/bin/loophole-trust-ca
COPY runtime.py /usr/local/lib/loophole/runtime.py

ENV PLAYWRIGHT_PORT=3000

EXPOSE 3000

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/docker-entrypoint.sh"]

CMD ["sh", "-c", "exec playwright run-server --port \"${PLAYWRIGHT_PORT}\" --host 0.0.0.0"]
