import base64
import http.client
import os
import pwd
import signal
import socket
import ssl
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from managed_service import Service

ENTRYPOINT = "/usr/local/bin/docker-entrypoint.sh"
PASSTHROUGH_STATUS = 23


def environment(tmp_path, **overrides):
    return {
        **os.environ,
        "HOME": str(tmp_path),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "LOOPHOLE_ENABLED": "1",
        "LOOPHOLE_CA_CERT": "",
        "LOOPHOLE_CA_CERT_B64": "",
        "LOOPHOLE_MAP": "",
        "LOOPHOLE_MAP_FILE": "",
        **overrides,
    }


def entrypoint(tmp_path, **overrides):
    return subprocess.run(
        [ENTRYPOINT, "sh", "-c", f"exit {PASSTHROUGH_STATUS}"],
        env=environment(tmp_path, **overrides),
        capture_output=True,
        text=True,
        timeout=45,
    )


@pytest.mark.parametrize(
    "routes",
    [
        "{}",
        "[]",
        "not a map",
        "[unclosed",
        '"web:8000": app.test\n"web:8000": other.test',
        '"web:8000": app.test\n"other:8000": APP.test',
        '"web:0": app.test',
        '"web:65536": app.test',
        '"http://web:8000": app.test',
        '"web:8000": "bad/name"',
        '"127.0.0.1:443": app.test',
        '"app.test:80": app.test',
        '"web:8000": [app.test]',
    ],
)
def test_invalid_routes_stop_before_command(tmp_path, routes):
    result = entrypoint(tmp_path, LOOPHOLE_MAP=routes)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ValueError" in result.stderr or "yaml.parser.ParserError" in result.stderr
    assert not (tmp_path / "state").exists()


def test_two_map_sources_rejected(tmp_path):
    result = entrypoint(tmp_path, LOOPHOLE_MAP='"web:8000": app.test', LOOPHOLE_MAP_FILE="/absent")
    assert result.returncode == 1
    assert "only one" in result.stderr


def test_disabled_ignores_map(tmp_path):
    result = entrypoint(tmp_path, LOOPHOLE_ENABLED="0", LOOPHOLE_MAP="malformed")
    assert result.returncode == PASSTHROUGH_STATUS


def test_nonroot_managed_mode_is_rejected(tmp_path):
    result = subprocess.run(
        [ENTRYPOINT, "true"],
        env=environment(tmp_path, LOOPHOLE_MAP='"web:8000": app.test'),
        user=pwd.getpwnam("pwuser").pw_uid,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "requires root" in result.stderr


@pytest.fixture
def running_localias(tmp_path):
    "start managed mode against sibling services and an IPv6 loopback upstream"

    class IPv6Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    server = IPv6Server(("::1", 0), Service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    routes = (
        '"managed-one:8000": one.loophole.test\n'
        '"managed-two:8000": two.loophole.test\n'
        f'"[::1]:{server.server_port}": ipv6.loophole.test\n'
        '"unavailable:8000": unavailable.loophole.test\n'
    )
    ready = tmp_path / "ready"
    log = (tmp_path / "localias.log").open("w+")
    env = environment(tmp_path, LOOPHOLE_MAP=routes, READY=str(ready))
    process = subprocess.Popen(
        [ENTRYPOINT, "sh", "-c", 'touch "$READY"; exec sleep 300'],
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 40
        while not ready.exists():
            assert process.poll() is None, (tmp_path / "localias.log").read_text()
            assert time.monotonic() < deadline, (tmp_path / "localias.log").read_text()
            time.sleep(0.1)
        yield process, env
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
        process.wait(timeout=10)
        log.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_direct_routing_trust_and_websocket(running_localias, playwright, tmp_path, artifacts):
    process, env = running_localias
    browser = playwright.chromium.launch(env=env)
    try:
        page = browser.new_page()
        for domain, upstream in [("one", "one"), ("two", "two"), ("ipv6", "ipv6")]:
            hostname = f"{domain}.loophole.test"
            assert socket.gethostbyname(hostname) == "127.0.0.1"
            response = page.goto(f"https://{hostname}")
            assert response.status == 200
            assert response.json() == {"upstream": upstream, "host": hostname}
        page.screenshot(path=artifacts / "service.png")
        assert (
            page.evaluate("""() => new Promise((resolve, reject) => {
            const socket = new WebSocket('wss://one.loophole.test/ws');
            socket.onmessage = event => { resolve(event.data); socket.close(); };
            socket.onerror = reject;
        })""")
            == "upstream websocket reached"
        )
        page.goto("http://one.loophole.test")
        assert page.url == "https://one.loophole.test/"
    finally:
        browser.close()
    configs = list(Path("/tmp").glob("loophole.*/localias.yaml"))
    assert any("managed-one:8000" in config.read_text() for config in configs)
    assert not subprocess.run(["pgrep", "-x", "haproxy"], capture_output=True).stdout
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=10) == 143


def test_ipv6_browser_facing_tls(running_localias):
    _, env = running_localias
    ca = subprocess.check_output(["localias", "debug", "cert"], env=env, text=True).strip()
    context = ssl.create_default_context(cafile=ca)
    with socket.create_connection(("::1", 443), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname="one.loophole.test") as stream:
            stream.sendall(
                b"GET / HTTP/1.1\r\nHost: one.loophole.test\r\nConnection: close\r\n\r\n"
            )
            response = http.client.HTTPResponse(stream)
            response.begin()
            assert response.status == 200


@pytest.mark.parametrize("source", ["inline", "file"])
def test_exit_status_cleanup_and_persisted_ca(tmp_path, source):
    routes = '"unavailable:8000": restart.loophole.test'
    overrides = {"LOOPHOLE_MAP": routes}
    if source == "file":
        config = tmp_path / "routes.yaml"
        config.write_text(routes)
        config.chmod(0o444)
        overrides = {"LOOPHOLE_MAP_FILE": str(config)}
    roots = []
    for _ in range(2):
        result = entrypoint(tmp_path, **overrides)
        assert result.returncode == PASSTHROUGH_STATUS, result.stdout + result.stderr
        roots.append(next((tmp_path / "state").rglob("root.crt")).read_bytes())
        assert "localias https ready" in result.stderr
    assert roots[0] == roots[1]
    if source == "file":
        assert config.read_text() == routes


def test_external_ca_overrides_map(tmp_path):
    result = entrypoint(tmp_path, LOOPHOLE_MAP='"unavailable:8000": external.loophole.test')
    assert result.returncode == PASSTHROUGH_STATUS, result.stdout + result.stderr
    ca = next((tmp_path / "state").rglob("root.crt"))
    for overrides in [
        {"LOOPHOLE_CA_CERT": str(ca)},
        {
            "LOOPHOLE_CA_CERT_B64": base64.b64encode(ca.read_bytes()).decode(),
            "LOOPHOLE_CA_CERT": "/absent",
        },
    ]:
        result = entrypoint(
            tmp_path, LOOPHOLE_MAP="invalid", LOOPHOLE_TARGET_IP="127.0.0.1", **overrides
        )
        assert result.returncode == PASSTHROUGH_STATUS, result.stderr
        assert "ignoring LOOPHOLE_MAP" in result.stdout
    default_ca = Path("/usr/local/share/ca-certificates/localias.crt")
    assert not default_ca.exists()
    try:
        default_ca.write_bytes(ca.read_bytes())
        result = entrypoint(tmp_path, LOOPHOLE_MAP="invalid", LOOPHOLE_TARGET_IP="127.0.0.1")
        assert result.returncode == PASSTHROUGH_STATUS, result.stderr
        assert "ignoring LOOPHOLE_MAP" in result.stdout
    finally:
        default_ca.unlink()


def test_proxy_death_stops_command(running_localias):
    process, _ = running_localias
    proxy_pid = int(subprocess.check_output(["pgrep", "-x", "localias"], text=True).strip())
    os.kill(proxy_pid, signal.SIGKILL)
    assert process.wait(timeout=10) == 1


def test_listener_conflict(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 443))
        listener.listen()
        result = entrypoint(tmp_path, LOOPHOLE_MAP='"unavailable:8000": conflict.loophole.test')
    assert result.returncode == 1
    assert "before readiness" in result.stderr


def test_readiness_timeout_stops_proxy_and_command(tmp_path):
    executable = tmp_path / "localias"
    executable.write_text(
        '#!/bin/sh\nif [ "$3" = debug ]; then echo /absent-ca; exit 0; fi\n'
        'exec /usr/local/bin/localias "$@"\n'
    )
    executable.chmod(0o755)
    start = time.monotonic()
    result = entrypoint(
        tmp_path,
        LOOPHOLE_MAP='"unavailable:8000": timeout.loophole.test',
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    assert result.returncode == 1
    assert "within 30s" in result.stderr
    assert 30 <= time.monotonic() - start < 40
    assert not subprocess.run(["pgrep", "-x", "localias"], capture_output=True).stdout


def test_failed_generated_ca_import_stops_immediately(tmp_path):
    start = time.monotonic()
    result = entrypoint(
        tmp_path,
        HOME="/proc",
        LOOPHOLE_MAP='"unavailable:8000": trust-failure.loophole.test',
    )
    assert result.returncode == 1
    assert "loophole-trust-ca" in result.stderr
    assert time.monotonic() - start < 10
