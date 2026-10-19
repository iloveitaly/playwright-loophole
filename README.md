# playwright-loophole

A Playwright Docker image that forwards container loopback TCP traffic on ports 80
and 443 to localias on your host. TLS passes through unchanged, preserving SNI and
HTTP Host headers. IPv6 loopback listeners are enabled when the namespace has ::1.

```sh
docker build -t playwright-loophole:local .
docker run --rm --add-host=host.docker.internal:host-gateway \
  -p 127.0.0.1:3000:3000 playwright-loophole:local
```

Use `compose.example.yaml` with `docker compose -f compose.example.yaml up --build`.
Other services connect using `chromium.connect('ws://chrome:3000')`. Match your
client Playwright version to the image version. The image installs the matching
npm driver and test runner at build time; startup requires no npm downloads.
Override the command normally, for example `docker run ... IMAGE node --version`.
Use `--user pwuser` for non-root execution; HAProxy has the bind-service capability.
The default image runs as root, matching upstream.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `LOOPHOLE_ENABLED` | `1` | Set `0` to bypass relay startup, including host networking. |
| `LOOPHOLE_TARGET_IP` | auto | Literal IPv4/IPv6 host address override. |
| `LOOPHOLE_HTTP_PORT` | `80` | HTTP listener and target port. |
| `LOOPHOLE_HTTPS_PORT` | `443` | HTTPS listener and target port. |
| `LOOPHOLE_CA_CERT` | `/usr/local/share/ca-certificates/localias.crt` | Optional root CA to import into the current user's NSS database. |
| `PLAYWRIGHT_PORT` | `3000` | Default server port. Update Docker port publishing if changed. |

Host discovery prefers `host.docker.internal`, then the IPv4 default gateway.
Docker Desktop and OrbStack normally provide the host name; native Linux can use
`--add-host=host.docker.internal:host-gateway`. The host service must listen on an
address reachable from the container; on native Linux a service bound exclusively
to host loopback cannot be reached through the bridge gateway. Use host networking
and `LOOPHOLE_ENABLED=0`, or configure localias to listen on the bridge-reachable
address. Loopback target overrides automatically bypass the relay.

Mount the localias root CA read-only at the default certificate path (see Compose).
It is imported into `$HOME/.pki/nssdb`, even with forwarding disabled. Ensure HOME
points at a writable directory for the selected user. CA import failures stop
startup. This configures Chromium trust; curl uses `--cacert` separately.

Managed policies in `/etc/chromium/policies/managed` and
`/etc/opt/chrome/policies/managed` set `QuicAllowed` to false. Tests need no
`--disable-quic` argument. Verify policy loading for your selected browser/channel;
the policy test uses full Chromium (`channel: 'chromium'`) so chrome://policy is
available. Firefox and WebKit do not use these policies or Chromium's NSS store.

HAProxy daemon startup returns only after binding its listeners. Listener conflicts
fail startup before running the command. A small shell supervisor preserves command
exit status and stops HAProxy on exit; tini reaps adopted children and forwards
signals to the process group. Runtime config uses a private temporary directory.

## End-to-end test (`just test`)

Run on a Linux Docker host, including GitHub Actions `ubuntu-latest`, with
Docker, Python 3, and [Just](https://just.systems/) installed:

```sh
just test
# Optional: select an upstream image/browser version.
PLAYWRIGHT_VERSION=v1.50.0-noble just test
```

The runner builds the shipping image, then a derived test image containing Python,
a Playwright client matching the server's major/minor version, and `python-hosts`. It starts an HTTP service on the
runner at an automatically assigned port and starts the container using its default
Playwright server command. No localias installation or host-side pip install is
required. Docker must use a local daemon reachable from the runner.

Inside the container, `python-hosts` adds `service.loophole.test` to `/etc/hosts`,
pointing at `127.0.0.1`. The Python browser script connects to the Playwright server
and visits `http://service.loophole.test:<port>/`. That request must traverse
HAProxy and the host gateway to reach the separate service. The fixture checks
the HTTP Host header and returns unique text for each test run.

The test asserts HTTP 200, the expected page text, and an existing, nonempty PNG
screenshot. It also exports and checks the screenshot on the runner and verifies
that the host service received a request. There are no optional skips in this test.
`python-hosts` removes the entry in a `finally` block and checks that it is gone.
The runner stops the service and removes the container on success or failure;
the runner's own `/etc/hosts` is never modified. Test images remain for debugging.

Artifacts are saved to `test-results/end-to-end/<run-id>/service.png` and
`container.log`. A screenshot is also collected on assertion failure if capture
succeeded. For GitHub Actions, run `just test` after checkout and Just setup, then
use `actions/upload-artifact` with `if: always()` and the path
`test-results/end-to-end/`. The `Build and Test` workflow in `.github/workflows/build.yml` runs these steps
on pushes to main/master, pull requests, and manual dispatch.

The suite has passed in GitHub Actions; it has not been executed locally. It covers HTTP through a custom hosts entry. The existing
verification below provides additional TLS, IPv6, CA trust, and policy coverage.

## Verification

With localias serving an HTTPS URL whose root certificate you have mounted:

```sh
docker run --rm --user pwuser \
  --add-host=host.docker.internal:host-gateway \
  -v "$PWD/test:/verification:ro" \
  -v "$LOCALIAS_CA_PATH:/usr/local/share/ca-certificates/localias.crt:ro" \
  -e LOOPHOLE_CA_CERT=/usr/local/share/ca-certificates/localias.crt \
  -e LOOPHOLE_TEST_URL=https://api-test.myproject.localhost \
  -w /verification playwright-loophole:local \
  playwright test --workers=1 --output=/tmp/test-results
```

The suite verifies policy value/status, IPv4 and IPv6 TLS relay (including SNI),
and browser navigation without ignoring certificate errors. IPv6 must be enabled
for the dual-stack acceptance check. Run once as root and once as pwuser. The relay
checks require your running host service; without LOOPHOLE_TEST_URL they skip.

Run `node --test test/entrypoint.test.cjs` for isolated startup regression tests.
For a self-contained relay/TLS/NSS check without localias, run:

```sh
docker run --rm --user pwuser -e LOOPHOLE_ENABLED=0 \
  -v "$PWD/test:/verification:ro" playwright-loophole:local \
  node /verification/relay-integration.cjs
```

This fixture binds the container's non-loopback address as a stand-in for the host,
creates a temporary CA, and starts the real entrypoint to test both loopback
families on ports 80/443. It does not test platform host gateway discovery.
Repeat without `--user pwuser` for root coverage.

For lifecycle verification, run the server, send `docker stop --time 10`, and inspect
its exit status/logs; repeat with `docker kill --signal=INT`.

## Published images and weekly builds

Images are published to `ghcr.io/iloveitaly/playwright-loophole` for `linux/amd64`
and `linux/arm64`. Replace the upstream registry/repository and keep the tag:

```yaml
image: ghcr.io/iloveitaly/playwright-loophole:v1.64.1-noble
```

`Build and Publish Images` runs every Monday at **06:23 UTC**. It discovers the
latest stable release directly from MCR, then builds all available supported
variants: `vX.Y.Z`, `vX.Y.Z-noble`, `vX.Y.Z-jammy`, and `vX.Y.Z-resolute`.
Prerelease and unsupported distribution tags are excluded. This tracks the latest
stable release, rather than rebuilding the entire historical upstream catalog.
Previously published releases remain available.

Each variant builds on native AMD64 and ARM64 GitHub runners. The Python browser
suite tests the exact uploaded digest for each architecture before any version
tags are published. It verifies the host relay, page text, screenshot, and hosts
entry cleanup. Screenshots/logs are uploaded per variant and architecture.
Only after every build/test succeeds does the workflow publish the multi-platform
version tags and matching upstream-style `-amd64` and `-arm64` tags. Failed tests
can leave untagged build digests in GHCR but do not update public version tags.

Weekly builds refresh the selected version's OS packages even if upstream has not
released a new Playwright version. Version tags therefore move on rebuild; pin an
image digest when immutable deployments are required. No `latest` alias is added.
Your Playwright client major/minor version must match the image's version
([protocol compatibility](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect)).
Python does not necessarily publish every patch version released for Node.

To publish immediately, or backfill another supported stable release:

```sh
gh workflow run publish.yml                       # newest stable upstream release
gh workflow run publish.yml -f version=v1.50.0    # all available variants of this release
```

Publishing uses the repository's `GITHUB_TOKEN` with job-scoped `packages: write`;
no additional registry secret is required. GHCR package visibility is independent
of repository visibility: if the initial package is private, set its visibility
to public in the package settings to permit anonymous pulls.

For a manual local build (not part of the CI test procedure):

```sh
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg PLAYWRIGHT_VERSION=v1.50.0-noble \
  -t ghcr.io/iloveitaly/playwright-loophole:v1.50.0-noble --push .
```

Native Linux hosts using ufw/firewalld must allow Docker bridge traffic to the
localias TCP ports. For the default bridge, an example is
`ufw allow in on docker0 to any port 443 proto tcp`; also allow port 80 if needed.
Compose networks may use a different bridge interface. Scope firewall rules to
that interface or subnet.

References: [upstream image contents/version matching](https://playwright.dev/docs/docker)
and [Chromium Linux managed policies](https://www.chromium.org/administrators/linux-quick-start/).
