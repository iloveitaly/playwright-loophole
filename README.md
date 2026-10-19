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

Managed policies in `/etc/chromium/policies/managed`,
`/etc/opt/chrome/policies/managed`, and
`/etc/opt/chrome_for_testing/policies/managed` set `QuicAllowed` to false. Tests
need no `--disable-quic` argument. Verify policy loading for your selected
browser/channel; the policy test uses full Chromium (`channel: 'chromium'`) so
chrome://policy is available. Firefox and WebKit do not use these policies or
Chromium's NSS store.

HAProxy daemon startup returns only after binding its listeners. Listener conflicts
fail startup before running the command. A small shell supervisor preserves command
exit status and stops HAProxy on exit; tini reaps adopted children and forwards
signals to the process group. Runtime config uses a private temporary directory.

## Tests and tooling

Install [mise](https://mise.jdx.dev/) and a local Docker Engine. Tool versions are
configured in `mise.toml`, following the Python package template's conventions:
Python 3.12, uv, Just, GitHub CLI, and jq. Python packages live in `pyproject.toml`
and `uv.lock`; uv creates and manages all Python environments and dependencies.

```sh
mise install
mise exec -- just setup
mise exec -- just lint
mise exec -- just test
# Optional: choose another upstream release.
PLAYWRIGHT_VERSION=v1.64.1-noble mise exec -- just test
```

All tests are Python/pytest and run through `just test` on a Linux Docker host.
GitHub Actions installs tools with `jdx/mise-action`, checks lint/formatting, and
runs the suite. No browser tests run on the host. Node/npm remain part of the
shipping Playwright runtime; they are not used to execute this repository's tests.

The runner builds the shipping image, then a derived test image using uv-managed
Python and the locked test dependencies. It constrains the Python Playwright client
to the server's major/minor version inside the test image because Python may not
publish every Node patch release. The repository's lockfile is not modified by
this per-image resolution. Python 3.12 supports the older Playwright client releases
used when backfilling upstream image tags.

The runner starts separate HTTP and HTTPS services on the host with a temporary
root CA and signed server certificate. Each service checks the HTTP Host header;
the HTTPS service also checks TLS SNI. The real entrypoint imports the CA and
forwards loopback traffic to these services through the discovered host gateway.
No localias installation, existing CA, or host `/etc/hosts` modification is needed.

The complete suite runs once as root and once as pwuser:

- `test/test_entrypoint.py`: bypass behavior, exit codes, malformed addresses and
  ports, CA import/failure, listener conflicts, and synchronous readiness on 80/443.
- `test/test_relay.py`: verified HTTP/HTTPS connections over IPv4 and IPv6 loopback,
  preserving Host and TLS SNI.
- `test/test_browser.py`: custom-host HTTP navigation, a nonempty PNG screenshot,
  expected page text, HTTPS navigation with NSS trust, and the loaded QUIC policy.

The `python-hosts` tool in `test/hosts.py` adds `service.loophole.test` to the
container hosts file and removes it in cleanup, verifying both operations. Only
this operation runs as root in the pwuser case; pytest and the browsers run as
pwuser. HTTPS browser navigation uses `fixture.localhost`, exercising Chromium's
internal localhost resolver without a hosts override or ignored certificate errors.
IPv6 loopback must be available; checks fail rather than silently skipping coverage.

Screenshots, JUnit reports, and container logs are exported to
`test-results/end-to-end/<run-id>/<user>/` and uploaded by Actions even on failure.
The runner removes containers and stops host services on success or failure;
derived test images remain for debugging. Tests are verified in GitHub Actions,
not executed locally during development.

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
tags are published. It runs the full root/pwuser suite, including IPv4/IPv6 forwarding, TLS
trust and SNI, QUIC policy, page text, screenshots, and hosts entry cleanup. Screenshots/logs are uploaded per variant and architecture.
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
