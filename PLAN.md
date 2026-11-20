# Container-managed localias mode

Add an alternative startup mode that runs localias inside the Playwright container. Activate it only when a nonempty route map is supplied and no external CA is supplied. Keep the existing host relay as the default.

Use the direct upstream support released in [`iloveitaly/localias` v3.1.0](https://github.com/iloveitaly/localias/releases/tag/v3.1.0), built from commit `5df568f6262824da9c57725eeeffe39963bf789e` on the `localias-upstream` branch. Its embedded Caddy connects directly to each configured upstream. HAProxy runs only in the existing host relay mode.

## Configuration

Accept YAML through `LOOPHOLE_MAP`:

```yaml
services:
  chrome:
    image: playwright-loophole:local
    environment:
      LOOPHOLE_MAP: |
        "172.18.0.5:8000": app.test
        "172.18.0.6:5173": frontend.test
    ports:
      - "127.0.0.1:3000:3000"
    shm_size: 1gb
```

Keys are upstream endpoints and values are domain names, matching the requested `ip:port => domain` direction. Also accept resolvable service names such as `web:8000`, which are more stable than container IPs in Compose. Use plain domains without schemes, paths, or ports. Upstream connections use HTTP in the first version; browser-facing connections use HTTPS.

Endpoints use the fork's explicit `host:port` syntax, without schemes or paths; IPv6 addresses require brackets, for example `"[fd00::5]:8000"`. Reverse the input mapping when generating localias's native configuration:

```yaml
app.test: "172.18.0.5:8000"
frontend.test: "172.18.0.6:5173"
```

Write this generated file to a private writable runtime directory. Localias opens its configuration read/write, so do not pass the user's read-only source mount directly. Caddy resolves upstream hostnames when connecting; do not require DNS resolution or application availability while validating the input map.

For longer configurations, also accept `LOOPHOLE_MAP_FILE=/config/routes.yaml`, pointing to a read-only mounted YAML file with the same shape. Reject simultaneous map and map-file inputs. Never modify the source file.

Use distribution-packaged Python and PyYAML, installed at image build time. Reject malformed YAML, duplicate keys, empty maps, duplicate domain values, invalid endpoints, and invalid domain names before starting processes. An explicitly supplied invalid map is an error when managed mode is selected; it must not silently fall back to host forwarding. Reject listener/endpoint combinations that would create a forwarding loop.

## Mode selection and certificate precedence

Determine the mode before generating certificates or starting listeners:

| Inputs | Behavior |
| --- | --- |
| `LOOPHOLE_ENABLED=0` | Import an externally supplied CA as today; skip both relay and managed localias startup. |
| Nonempty `LOOPHOLE_CA_CERT_B64` | Import that CA and use the existing host relay; ignore map inputs. |
| Explicit nonempty `LOOPHOLE_CA_CERT` | Import that CA and use the existing host relay; ignore map inputs. |
| CA file exists at the existing default path | Import that CA and use the existing host relay; ignore map inputs. |
| No external CA, map supplied | Start container-managed localias mode. |
| No external CA, no map | Use existing host relay behavior. |

`LOOPHOLE_CA_CERT_B64` retains precedence over the certificate path. An explicitly supplied missing, unreadable, or invalid certificate must fail startup, rather than activate managed mode. Checking the default mount path preserves existing certificate-volume setups. A generated CA must live outside that default path so it cannot accidentally select host relay mode on restart.

Log the selected mode. When an external CA takes precedence, log that map inputs are ignored without parsing them. `LOOPHOLE_TARGET_IP`, `LOOPHOLE_HTTP_PORT`, and `LOOPHOLE_HTTPS_PORT` continue to configure only the existing host relay. Managed mode uses standard localias ports 80/443.

## Request path and direct upstream routing

```text
Chromium: https://app.test
  -> container loopback:443, resolved through localias-managed /etc/hosts
  -> localias/Caddy: TLS termination with locally generated certificate
  -> configured upstream, for example 172.18.0.5:8000
```

The fork accepts a domain mapped to an explicit upstream address and generates Caddy's `reverse_proxy <host>:<port>` directly. Generate that native YAML configuration from the input map and run the released binary without additional patches.

Managed mode starts localias as its sole proxy process. It needs no HAProxy configuration, private adapter ports, or host discovery. Localias owns ports 80/443 and reports listener conflicts as startup failures. Keep the existing HAProxy package and relay configuration for host relay mode.

Preserve the original domain through the reverse proxy, and verify it with an upstream fixture. Include WebSocket coverage for development servers. Localias may redirect browser HTTP requests to HTTPS; document and test its actual behavior rather than promising HTTP passthrough.

## Startup, trust, and shutdown

1. Select the mode and validate managed configuration.
2. Create private runtime/configuration directories and a writable localias state directory.
3. Generate native localias YAML mapping each domain directly to its upstream endpoint.
4. Validate the generated configuration with `localias --configfile <generated-file> list --json`, which loads the saved file through the fork's target parser. This checks configuration only, not proxy readiness.
5. Run `localias --configfile <generated-file> run` under the entrypoint supervisor. Localias updates the container's `/etc/hosts` and generates its CA and domain certificates.
6. Wait with a bounded timeout for localias listeners and its generated root CA. Check process health during the wait and surface startup failures immediately.
7. Find the CA using `localias --configfile <generated-file> debug cert` with the same state environment. Import it using the existing NSS trust helper into the browser user's database.
8. Probe TLS with a configured domain as SNI and validate against the generated CA. Certificates are issued on demand, so file existence alone is insufficient readiness evidence. Do not require the application upstream to be healthy just to start Playwright.
9. Start the existing command, normally the Playwright WebSocket server.

Extract certificate import into a shared helper so supplied and generated certificates use the same code. The generated CA is container-local; no export, host trust installation, or ignored browser certificate errors are needed. Retain the existing QUIC policy and Chromium-only trust scope.

Use the existing `tini` process-group behavior. Supervise the selected proxy (localias in managed mode, HAProxy in host relay mode) alongside the main command. The main command exiting stops the proxy, signals reach every process, and unexpected proxy exit stops the container with a failure. Remove temporary configurations on exit. Keep localias state in a separate writable directory so it can optionally be persisted without putting CA private keys into configuration mounts. Confirm restart behavior with persisted state.

## Image and privilege requirements

- Install `iloveitaly/localias` release `v3.1.0` at image build time. Select `localias-linux-amd64` or `localias-linux-arm64` using Docker's target architecture, download from the fork's versioned release URL, verify the pinned SHA-256, and install it as `localias`. Do not use the upstream repository's binaries, a moving branch, or a `latest` download URL. No runtime downloads.
- Pin the release asset checksums: amd64 `67ad8e63df718f91e72a890881aba79dbd54f8e5d4c8cdf364a8f344953cfd95`; arm64 `fa055ccaee487e5875865c96d1bb52d4c66bbe521b76258c2aa1db5ad49b2f37`. These are the digests published by GitHub for the fork's `v3.1.0` assets; version upgrades must update both pins together.
- Treat the fork-specific download/checksum block as temporary. Switch to a pinned upstream release and revisit the block once all fork improvements (Caddy upgrade, JSON CLI output, and direct upstream support) are merged into upstream master/main and released. `TARGETARCH` itself is standard Docker architecture selection.
- Install `python3`, `python3-yaml`, and `python3-click` at image build time. Keep test dependencies in the derived test image.
- Include `sudo` in the image because the fork invokes `sudo tee` to update `/etc/hosts`, even when launched by root. Run managed mode as root without adding passwordless sudo rules for `pwuser`.
- Initially require root for managed mode because localias must edit `/etc/hosts` and initialize trust. The image already defaults to root. Preserve existing `--user pwuser` behavior in host relay mode; fail early with a specific explanation if managed mode is requested as `pwuser`.
- Do not require privileged Docker mode or host networking. Verify localias can update Docker's mounted `/etc/hosts` in place. Never mount the host's `/etc/hosts` into the container.
- Keep ports 80/443 internal; publish only the Playwright server port unless the user explicitly needs external access to the proxy.

## Implementation layout

- `Dockerfile`: fork release and architecture-specific checksum pins, YAML parser, and required runtime executable dependencies; retain HAProxy for host relay mode.
- `docker-entrypoint.sh`: mode selection, common trust import, and supervision for the selected mode.
- Small Python helper: parse/validate YAML, generate native localias YAML, check TLS readiness, and supervise child processes with `subprocess` and `signal`. Pass configuration as data, without shell interpolation. Keep host relay HAProxy configuration generation in its existing mode.
- `compose.example.yaml`: demonstrate managed mode using a YAML block and a separate file-mount example.
- `README.md`: activation table, request path, examples, root requirement, and upstream connectivity rules.

## Verification

Keep existing host relay coverage passing as root and `pwuser`. Add tests for:

- Every mode-selection row, including map plus external CA, default-mounted CA, invalid explicit CA, and disabled forwarding.
- YAML parsing and validation, both inline and file inputs, with malformed maps failing before listener startup.
- Two domains routing directly through localias to distinct upstream servers with preserved HTTP Host headers. Verify generated YAML contains the actual upstream endpoints, and no HAProxy process or private adapter listeners start in managed mode.
- Container `/etc/hosts` updates performed by localias; no test helper adding those domain entries.
- Chromium HTTPS navigation and screenshots with generated CA trust and no ignored HTTPS errors.
- IPv4 and IPv6 upstream targets, browser navigation through available IPv6 loopback, Compose service-name targets, and a WebSocket round trip.
- Localias startup failure, proxy death, port conflicts, bounded readiness failure, command exit codes, and shutdown cleanup. An unavailable application upstream must not fail the TLS-only startup readiness check.
- Managed mode rejecting `pwuser` without changing host relay support.
- Fresh and persisted localias state on restart, including correct mode selection and trust import.
- Both image architectures in the existing CI matrix, including the pinned release asset installation and checksum verification.

Run managed-mode integration tests with applications in sibling containers on an isolated Docker network, with no external CA and no host localias. This directly demonstrates that host-side redirection is unnecessary.

## Connectivity limits

Every endpoint is interpreted from inside the browser container. `127.0.0.1` refers to that container. Host applications still need an address/interface reachable from Docker; a native Linux host service listening only on host loopback remains inaccessible across the bridge. Applications in sibling Compose services can use service DNS names without involving the host gateway.

## Fork references

- [Fork release v3.1.0](https://github.com/iloveitaly/localias/releases/tag/v3.1.0)
- [Direct upstream documentation on localias-upstream](https://github.com/iloveitaly/localias/blob/localias-upstream/README.md#configuration-file)
- [Release-pinned configuration and direct upstream generation](https://github.com/iloveitaly/localias/blob/5df568f6262824da9c57725eeeffe39963bf789e/pkg/config/config.go)
- [Release-pinned target parsing](https://github.com/iloveitaly/localias/blob/5df568f6262824da9c57725eeeffe39963bf789e/pkg/config/target.go)
- [Release-pinned foreground startup and hosts updates](https://github.com/iloveitaly/localias/blob/5df568f6262824da9c57725eeeffe39963bf789e/cmd/localias/root/run.go)
- [Release-pinned hosts-controller sudo behavior](https://github.com/iloveitaly/localias/blob/5df568f6262824da9c57725eeeffe39963bf789e/cmd/localias/shared/shared.go)
- [Release-pinned CA path discovery](https://github.com/iloveitaly/localias/blob/5df568f6262824da9c57725eeeffe39963bf789e/cmd/localias/debug/cert.go)
- [Fork sibling-container direct upstream integration test](https://github.com/iloveitaly/localias/tree/5df568f6262824da9c57725eeeffe39963bf789e/integration/sibling-container)
