import os
import socket
import subprocess
import sys

import pytest

ENTRYPOINT = "/usr/local/bin/docker-entrypoint.sh"


def run_entrypoint(tmp_path, overrides, command=None):
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "LOOPHOLE_ENABLED": "1",
        "LOOPHOLE_CA_CERT": str(tmp_path / "absent.crt"),
        "LOOPHOLE_TARGET_IP": "192.0.2.1",
        "LOOPHOLE_HTTP_PORT": "80",
        "LOOPHOLE_HTTPS_PORT": "443",
        **overrides,
    }
    return subprocess.run(
        [ENTRYPOINT, *(command or ["sh", "-c", "exit 23"])],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_disabled_preserves_command_status(tmp_path):
    result = run_entrypoint(tmp_path, {"LOOPHOLE_ENABLED": "0"})
    assert result.returncode == 23
    assert "skipping" in result.stdout


@pytest.mark.parametrize("address", ["127.0.0.1", "127.42.0.1", "::1"])
def test_loopback_override_bypasses_relay(tmp_path, address):
    result = run_entrypoint(tmp_path, {"LOOPHOLE_TARGET_IP": address})
    assert result.returncode == 23


@pytest.mark.parametrize("address", ["192.0.2.1\nfrontend injected", "not-an-ip"])
def test_invalid_address_stops_before_command(tmp_path, address):
    result = run_entrypoint(tmp_path, {"LOOPHOLE_TARGET_IP": address})
    assert result.returncode == 1
    assert "Invalid host IP" in result.stderr


@pytest.mark.parametrize("port", ["0", "65536", "443", "80\nmalicious", "-1"])
def test_invalid_or_conflicting_ports(tmp_path, port):
    result = run_entrypoint(tmp_path, {"LOOPHOLE_HTTP_PORT": port})
    assert result.returncode == 1


def test_ca_is_imported_even_when_relay_disabled(tmp_path):
    result = run_entrypoint(
        tmp_path,
        {
            "LOOPHOLE_ENABLED": "0",
            "LOOPHOLE_CA_CERT": os.environ["LOOPHOLE_CA_CERT"],
        },
    )
    assert result.returncode == 23, result.stderr
    trust = subprocess.run(
        ["certutil", "-d", f"sql:{tmp_path}/.pki/nssdb", "-L", "-n", "localias-loophole-ca"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert trust.returncode == 0, trust.stderr


def test_bad_ca_stops_before_command(tmp_path):
    cert = tmp_path / "broken.crt"
    cert.write_text("not a certificate")
    result = run_entrypoint(tmp_path, {"LOOPHOLE_CA_CERT": str(cert)})
    assert result.returncode != 0 and result.returncode != 23


def test_conflicting_listener_stops_before_command(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = run_entrypoint(tmp_path, {"LOOPHOLE_HTTP_PORT": str(port)})
    assert result.returncode != 0 and result.returncode != 23
    assert "cannot bind" in result.stderr.lower()


def test_privileged_listeners_are_ready_before_command(tmp_path):
    # Run an immediate connection check as the command, with no readiness polling.
    code = (
        "import socket; "
        "socket.create_connection(('127.0.0.1',80),timeout=1).close(); "
        "socket.create_connection(('127.0.0.1',443),timeout=1).close()"
    )
    result = run_entrypoint(tmp_path, {}, [sys.executable, "-c", code])
    assert result.returncode == 0, result.stderr
