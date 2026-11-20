# Proposal: Support explicit upstream addresses in localias

## Summary

Extend localias to accept `host:port` targets alongside existing local port numbers. Its embedded Caddy connects directly to the target, eliminating the need for an additional proxy.

Keep the change focused on HTTP upstreams. Certificate generation, browser-facing HTTPS, `/etc/hosts`, and mDNS behavior remain as they are.

## Configuration and CLI

Preserve existing YAML and allow address strings:

```yaml
# Existing syntax: HTTP upstream on localhost
app.test: 8000

# New syntax: HTTP upstream at an explicit address
api.test: "192.168.1.10:8000"
frontend.test: "frontend:5173"
ipv6.test: "[::1]:9000"
```

Keep localias's existing `domain → target` direction. Multiple domains can point to the same target.

Support these CLI forms:

```sh
# Existing forms remain supported
localias set app.test 8000
localias set --alias app.test --port 8000

# New forms
localias set api.test 192.168.1.10:8000
localias set --alias api.test --upstream 192.168.1.10:8000
```

Require `--alias` with exactly one of `--port` or `--upstream` when using flags. Reject mixing positional and flag-based inputs. Quoted numeric YAML values such as `"8000"` are treated as local ports and saved as integers.

## Implementation

### Configuration model and persistence

- Retain `Entry.Port` and add `Entry.Upstream string`. Exactly one represents the target.
- Introduce shared target parsing, validation, and display helpers used by YAML loading, CLI commands, persistence, and Caddy generation.
- Replace unchecked YAML type assertions with descriptive errors identifying the alias and invalid target.
- Preserve entry ordering and existing alias replacement/import behavior.
- Save local ports as YAML integers and explicit addresses as strings. Existing configurations need no migration.
- Update `list`, command confirmations, and `Entry.String()` to display either target form.

The current model and Caddy generation are in [the configuration implementation](https://github.com/peterldowns/localias/blob/main/pkg/config/config.go); YAML loading is in [the configuration loader](https://github.com/peterldowns/localias/blob/main/pkg/config/path.go).

### Validation

- Accept integer ports from 1–65535.
- Accept explicit addresses containing an IPv4 address, bracketed IPv6 address, or hostname plus a numeric port from 1–65535.
- Use Go's `net.SplitHostPort` and standard address parsing; require a nonempty host.
- Reject schemes, paths, credentials, whitespace, and Caddy configuration delimiters. Do not resolve hostnames during parsing.
- Do not add HTTPS upstreams, URL paths, Unix sockets, or arbitrary Caddy directives in this change.

### Caddy routing

Generate the upstream according to the configured target:

```caddyfile
# Existing integer target
reverse_proxy localhost:8000

# Explicit address target
reverse_proxy 192.168.1.10:8000
```

Keep existing TLS directives and alias handling. `/etc/hosts` continues to map the alias to localias itself; the upstream address never becomes the alias's hosts-file address.

Hostname targets use Caddy's normal DNS resolution. Connection failures remain ordinary reverse-proxy errors rather than preventing configuration loading.

## Tests and acceptance criteria

- Existing integer configurations produce the same Caddy configuration.
- Mixed integer/address YAML round-trips with ordering and target types preserved.
- IPv4, bracketed IPv6, and service-name targets generate valid Caddy configuration.
- Invalid target types and malformed addresses return errors without panicking.
- CLI positional and flag forms work; conflicting inputs fail.
- Listing, updating, and importing entries work when switching between port and address targets.
- An integration test proxies a request to a server listening on an explicit address and verifies the original HTTP Host header.
- A sibling-container integration test demonstrates `frontend:5173` routing without HAProxy.
- Existing certificate and hosts-management behavior continues to pass.

Document the new syntax and clarify that `localhost` always refers to the machine or container running localias. This proposal changes localias only; selection between host relay and container-managed routing remains the responsibility of playwright-loophole.
