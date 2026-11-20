"Configure localias and supervise the selected proxy and container command"

import ipaddress
import json
import logging
import os
import re
import signal
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

import click
import yaml

STARTUP_TIMEOUT = 30
SHUTDOWN_TIMEOUT = 5
POLL_INTERVAL = 0.1
PROBE_TIMEOUT = 1
HTTP_PORT = 80
HTTPS_PORT = 443
LOOPBACK_HOST = "127.0.0.1"
MAX_DOMAIN_LENGTH = 253
MAX_TCP_PORT = 65_535
SIGNAL_EXIT_OFFSET = 128
CA_TRUST_COMMAND_PATH = Path("/usr/local/bin/loophole-trust-ca")
YAML_STRING_TAG = "tag:yaml.org,2002:str"
DOMAIN_LABEL = re.compile(
    r"""
    # begin with a letter or digit
    [a-z0-9]
    (?:
        # optional remainder permits internal hyphens, up to 63 characters total
        [a-z0-9-]{0,61}
        # the last character must also be a letter or digit
        [a-z0-9]
    )?
    """,
    re.IGNORECASE | re.VERBOSE,
)
"Match one DNS label while excluding punctuation that could alter Caddy configuration"

ENDPOINT = re.compile(
    r"""
    # capture either bracketed IPv6 or a hostname/IPv4 address
    (?P<host> \[ [0-9a-f:.]+ \] | [a-z0-9._-]+ )
    :
    # capture the port for range validation and loop detection
    (?P<port> [0-9]+ )
    """,
    re.IGNORECASE | re.VERBOSE,
)
"Separate the upstream host and port without resolving service names through DNS"

log = logging.getLogger(__name__)


def read_routes() -> dict[str, str]:
    "Read a string-to-string YAML map without silently accepting duplicate keys"

    inline = os.environ.get("LOOPHOLE_MAP")
    filename = os.environ.get("LOOPHOLE_MAP_FILE")
    if inline and filename:
        raise ValueError("Supply only one of LOOPHOLE_MAP and LOOPHOLE_MAP_FILE.")

    source = Path(filename).read_text() if filename else inline
    document = yaml.compose(source, Loader=yaml.SafeLoader)
    if not isinstance(document, yaml.MappingNode) or not document.value:
        raise ValueError("Route map must be a nonempty YAML mapping.")

    endpoints = set()
    routes = {}
    for key, value in document.value:
        if (
            not isinstance(key, yaml.ScalarNode)
            or not isinstance(value, yaml.ScalarNode)
            or key.tag != YAML_STRING_TAG
            or value.tag != YAML_STRING_TAG
        ):
            raise ValueError("Upstream endpoints and domains must be strings.")

        endpoint, domain = key.value, value.value.lower()
        if endpoint in endpoints or domain in routes:
            raise ValueError("Duplicate upstream endpoint or domain.")

        if len(domain) > MAX_DOMAIN_LENGTH or not all(
            DOMAIN_LABEL.fullmatch(part) for part in domain.split(".")
        ):
            raise ValueError(f"Invalid domain: {domain}")

        endpoints.add(endpoint)
        routes[domain] = endpoint
    assert_valid_endpoints(routes)
    return routes


def assert_valid_endpoints(routes: dict[str, str]) -> None:
    "Reject malformed targets and loops without resolving upstream DNS names"

    interfaces = json.loads(subprocess.check_output(["ip", "-j", "address"]))
    local_addresses = {info["local"] for iface in interfaces for info in iface["addr_info"]}
    for endpoint in routes.values():
        match = ENDPOINT.fullmatch(endpoint)
        if not match or not 1 <= int(match["port"]) <= MAX_TCP_PORT:
            raise ValueError(f"Invalid upstream: {endpoint}")

        host = match["host"].strip("[]").lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if match["host"].startswith("["):
                raise ValueError(f"Invalid IPv6 upstream: {endpoint}") from None
            address = None
        mapped = getattr(address, "ipv4_mapped", None)
        local = (
            host in local_addresses
            or host in routes
            or host == "localhost"
            or host.endswith(".localhost")
        )
        local = local or (address and (address.is_loopback or address.is_unspecified))
        if int(match["port"]) in (HTTP_PORT, HTTPS_PORT) and (
            local or (mapped and mapped.is_loopback)
        ):
            raise ValueError(f"Upstream would loop back to localias: {endpoint}")


def wait_ready(config: Path, domains: Collection[str], proxy: subprocess.Popen[bytes]) -> Path:
    "Warm on-demand certificates with TLS handshakes, without contacting upstreams"

    ca_path = Path(
        subprocess.check_output(
            ["localias", "--configfile", config, "debug", "cert"],
            text=True,
        ).strip()
    )
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if proxy.poll() is not None:
            raise RuntimeError("Localias exited before readiness.")
        try:
            context = ssl.create_default_context(cafile=ca_path)
            with socket.create_connection((LOOPBACK_HOST, HTTP_PORT), timeout=PROBE_TIMEOUT):
                pass
            for domain in domains:
                with socket.create_connection(
                    (LOOPBACK_HOST, HTTPS_PORT), timeout=PROBE_TIMEOUT
                ) as connection:
                    with context.wrap_socket(connection, server_hostname=domain):
                        pass
            return ca_path
        except OSError:
            time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"Localias did not become ready within {STARTUP_TIMEOUT}s.")


def signal_group(process: subprocess.Popen[bytes], signum: int) -> None:
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def stop(process: subprocess.Popen[bytes]) -> None:
    "Terminate a process group, escalating after the shutdown timeout"

    signal_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=SHUTDOWN_TIMEOUT)
    except subprocess.TimeoutExpired:
        pass
    # also stop descendants when their parent has already exited
    signal_group(process, signal.SIGKILL)
    process.wait()


def supervise(command: Sequence[str], is_proxy_alive: Callable[[], bool]) -> int:
    "Stop the command when its proxy exits, and clean up the command's descendants"

    with subprocess.Popen(command, start_new_session=True) as process:
        try:
            while (return_code := process.poll()) is None:
                if not is_proxy_alive():
                    raise RuntimeError("Proxy exited unexpectedly; stopping command.")
                time.sleep(POLL_INTERVAL)
            return return_code if return_code >= 0 else SIGNAL_EXIT_OFFSET - return_code
        finally:
            stop(process)


def run_managed(command: Sequence[str]) -> int:
    "Trust localias certificates before starting the container command"

    routes = read_routes()
    with TemporaryDirectory(prefix="loophole.") as directory:
        config = Path(directory) / "localias.yaml"
        config.write_text(yaml.safe_dump(routes, sort_keys=False))
        config.chmod(0o600)
        localias = ["localias", "--configfile", config]
        subprocess.run([*localias, "list", "--json"], check=True, stdout=subprocess.DEVNULL)
        with subprocess.Popen([*localias, "run"], start_new_session=True) as proxy:
            try:
                ca_path = wait_ready(config, routes, proxy)
                subprocess.run([CA_TRUST_COMMAND_PATH, ca_path], check=True)
                log.info("localias https ready; generated ca trusted")
                return supervise(command, lambda: proxy.poll() is None)
            finally:
                stop(proxy)


def is_relay_alive(pid: int) -> bool:
    "Check that HAProxy exists and is not a zombie"

    try:
        # daemonized HAProxy can be a zombie until tini reaps it
        status = Path(f"/proc/{pid}/status").read_text()
    except FileNotFoundError:
        return False

    state = next(line for line in status.splitlines() if line.startswith("State:"))
    return state.split()[1] != "Z"


def interrupted(signum: int, _frame) -> None:
    raise SystemExit(SIGNAL_EXIT_OFFSET + signum)


@click.command(context_settings={"allow_interspersed_args": False})
@click.argument("mode", type=click.Choice(["managed", "relay"]))
@click.argument("arguments", nargs=-1, type=click.UNPROCESSED, required=True)
def main(mode: str, arguments: tuple[str, ...]) -> None:
    "Run a managed proxy or monitor the existing host relay"

    logging.basicConfig(level=logging.INFO, format="[playwright-loophole] %(message)s")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if mode == "managed":
        sys.exit(run_managed(arguments))

    pid, *command = arguments
    sys.exit(supervise(command, lambda: is_relay_alive(int(pid))))


if __name__ == "__main__":
    main()
