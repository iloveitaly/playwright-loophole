# playwright-loophole

A Playwright Docker image that forwards container loopback TCP traffic on ports 80
and 443 to localias on your host. TLS passes through unchanged, so SNI and HTTP
Host headers reach the host intact. The container also listens on IPv6 loopback
when the network namespace has `::1`.

```sh
docker build -t playwright-loophole:local .
docker run --rm --add-host=host.docker.internal:host-gateway \
  -p 127.0.0.1:3000:3000 playwright-loophole:local
```

For Docker Compose, run `docker compose -f compose.example.yaml up --build` (see
`compose.example.yaml`). Other services can connect to the browser server with
`chromium.connect('ws://chrome:3000')` as long as your client Playwright version
matches the image version. The image installs the matching npm driver and test
runner at build time, so container startup does not download anything from npm.

You can override the container command as usual, such as
`docker run ... IMAGE node --version`. The image runs as root by default to match
the upstream Playwright image, or you can pass `--user pwuser` to run as a
non-root user because the HAProxy binary has the `bind-service` capability.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `LOOPHOLE_ENABLED` | `1` | Set `0` to bypass relay startup, including under host networking. |
| `LOOPHOLE_TARGET_IP` | auto | Literal IPv4/IPv6 host address override. |
| `LOOPHOLE_HTTP_PORT` | `80` | HTTP listener and target port. |
| `LOOPHOLE_HTTPS_PORT` | `443` | HTTPS listener and target port. |
| `LOOPHOLE_CA_CERT` | `/usr/local/share/ca-certificates/localias.crt` | Optional root CA to import into the current user's NSS database. |
| `PLAYWRIGHT_PORT` | `3000` | Default server port. Update Docker port publishing if you change it. |

Host discovery checks `host.docker.internal` first and falls back to the IPv4
default gateway. Docker Desktop and OrbStack define `host.docker.internal`
automatically, while native Linux needs
`--add-host=host.docker.internal:host-gateway`. The host service must listen on
an address the container can reach. On native Linux, a service bound only to host
loopback is unreachable across the bridge gateway; either run the container with
host networking and `LOOPHOLE_ENABLED=0`, or configure localias to listen on the
bridge address. Setting `LOOPHOLE_TARGET_IP` to a loopback address automatically
bypasses the relay.

Mount the localias root CA read-only at `/usr/local/share/ca-certificates/localias.crt`
(as shown in `compose.example.yaml`). The entrypoint imports that certificate into
`$HOME/.pki/nssdb` even when forwarding is disabled, and stops startup if the
import fails. Make sure `HOME` points to a writable directory for the active user.
Chromium trusts certificates in `$HOME/.pki/nssdb`, while curl still requires
`--cacert`.

Managed policies in `/etc/chromium/policies/managed`,
`/etc/opt/chrome/policies/managed`, and
`/etc/opt/chrome_for_testing/policies/managed` set `QuicAllowed` to `false`, so
tests do not need `--disable-quic`. Check that your chosen browser and channel
load these policies; the policy test runs full Chromium (`channel: 'chromium'`)
so `chrome://policy` is available. Firefox and WebKit ignore both these policies
and Chromium's NSS database.

During startup, the HAProxy daemon waits until its listeners are bound before
returning, and any port conflict stops the container before your command runs. A
small shell supervisor stops HAProxy when the main command exits and preserves the
command's exit status, while `tini` reaps adopted child processes and forwards
signals to the process group. HAProxy writes its runtime configuration to a
private temporary directory.

## Tests and tooling

Install [mise](https://mise.jdx.dev/) and a local Docker Engine. `mise.toml` pins
Python 3.12, uv, Just, GitHub CLI, and jq. Python dependencies are declared in
`pyproject.toml` and locked in `uv.lock`, and uv manages the virtual environment.

```sh
mise install
mise exec -- just setup
mise exec -- just lint
mise exec -- just test
# Optional: choose another upstream release.
PLAYWRIGHT_VERSION=v1.64.1-noble mise exec -- just test
```

`just test` runs the pytest suite on a Linux Docker host, and GitHub Actions uses
`jdx/mise-action` to run linting, formatting checks, and the test suite. Browser
tests run inside containers instead of on the host. The shipping image keeps Node
and npm for the Playwright runtime, while this repository's tests run in Python.

The test runner builds the shipping image first and then builds a derived test
image with uv-managed Python and the locked test dependencies. Inside the test
image, it pins the Python Playwright client to the server's major and minor
version because the Python package does not always publish every Node patch
release. Resolving that version inside the test image leaves the repository's
`uv.lock` untouched. Python 3.12 remains compatible with the older Playwright
client releases needed when backfilling earlier upstream image tags.

On the host, the runner starts separate HTTP and HTTPS test servers backed by a
temporary root CA and signed server certificate. Both servers check the HTTP
`Host` header, and the HTTPS server also checks TLS SNI. Inside the container, the
entrypoint imports the temporary CA and forwards loopback traffic to the host
servers through the discovered gateway, so running the suite does not require
localias, an existing CA, or edits to the host's `/etc/hosts`.

The full suite runs once as `root` and once as `pwuser`:

- `test/test_entrypoint.py`: bypass behavior, exit codes, malformed addresses and
  ports, CA import and failure handling, listener conflicts, and synchronous
  readiness on ports 80 and 443.
- `test/test_relay.py`: HTTP and HTTPS connections over IPv4 and IPv6 loopback
  with `Host` header and TLS SNI checks.
- `test/test_browser.py`: custom-host HTTP navigation, a nonempty PNG screenshot,
  expected page text, HTTPS navigation using NSS trust, and the loaded QUIC policy.

`test/hosts.py` uses `python-hosts` to add `service.loophole.test` to the
container's `/etc/hosts` file and remove it during cleanup, checking both steps.
When testing as `pwuser`, only that hosts-file helper runs as root; pytest and the
browsers run as `pwuser`. HTTPS browser tests navigate to `fixture.localhost`,
which goes through Chromium's built-in localhost resolver without a hosts-file
entry or ignored certificate errors. The suite requires IPv6 loopback and fails
if `::1` is unavailable instead of skipping those checks.

The runner writes screenshots, JUnit reports, and container logs to
`test-results/end-to-end/<run-id>/<user>/`, and GitHub Actions uploads them even
when a test run fails. After each run, the runner stops the host servers and
removes test containers while leaving the derived test images in place for
debugging.

## Published images and weekly builds

Multi-platform images for `linux/amd64` and `linux/arm64` are published to
`ghcr.io/iloveitaly/playwright-loophole`. Swap out the upstream registry and
repository while keeping the same tag:

```yaml
image: ghcr.io/iloveitaly/playwright-loophole:v1.64.1-noble
```

The `Build and Publish Images` workflow runs every Monday at 06:23 UTC. It queries
MCR for the latest stable Playwright release and builds all available supported
variants (`vX.Y.Z`, `vX.Y.Z-noble`, `vX.Y.Z-jammy`, and `vX.Y.Z-resolute`),
skipping prereleases and unsupported distribution tags. Scheduled runs build only
the newest stable release, while older published releases stay in GHCR.

Each variant builds on native AMD64 and ARM64 GitHub runners. Before publishing
any version tags, the workflow runs the Python browser test suite (as both `root`
and `pwuser`) against the exact uploaded image digest on each architecture and
uploads the resulting screenshots and logs. Once every build and test passes, the
workflow publishes the multi-platform version tags along with matching
upstream-style `-amd64` and `-arm64` tags. If a test fails, the untagged build
digest may remain in GHCR, but public version tags are left unchanged.

Weekly builds update OS packages for the current Playwright release even when
upstream has not cut a new version, so version tags move on rebuild. The workflow
does not publish a `latest` alias; pin an image digest if you need immutable
deployments. Keep your Playwright client on the same major and minor version as
the image ([protocol compatibility](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect)),
since the Python package does not publish every patch version released for Node.

To publish immediately or backfill another supported stable release:

```sh
gh workflow run publish.yml                       # newest stable upstream release
gh workflow run publish.yml -f version=v1.50.0    # all available variants of this release
```

Publishing uses the repository's `GITHUB_TOKEN` with job-scoped `packages: write`
permissions and needs no extra registry secret. GHCR package visibility is
configured separately from repository visibility, so if the initial package is
created as private, switch it to public in the package settings to allow
anonymous pulls.

To build and push multi-platform images manually from a local machine:

```sh
docker buildx build --platform linux/amd64,linux/arm64 \
  --build-arg PLAYWRIGHT_VERSION=v1.50.0-noble \
  -t ghcr.io/iloveitaly/playwright-loophole:v1.50.0-noble --push .
```

On native Linux hosts running ufw or firewalld, allow traffic from the Docker
bridge to the localias TCP ports. For the default `docker0` bridge, run
`ufw allow in on docker0 to any port 443 proto tcp` (and port 80 if needed).
Docker Compose networks create their own bridge interfaces, so scope firewall
rules to the matching interface or subnet.

References: [upstream image contents/version matching](https://playwright.dev/docs/docker)
and [Chromium Linux managed policies](https://www.chromium.org/administrators/linux-quick-start/).
