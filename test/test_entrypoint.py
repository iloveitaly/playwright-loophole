import base64
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ENTRYPOINT = "/usr/local/bin/docker-entrypoint.sh"
CA_NICKNAME = "localias-loophole-ca"
DEFAULT_TARGET_IP = "192.0.2.1"
LOOPBACK_IPV4 = "127.0.0.1"
DEFAULT_HTTP_PORT = "80"
DEFAULT_HTTPS_PORT = "443"

DISABLED_LOOPHOLE = "0"
ENABLED_LOOPHOLE = "1"

SUCCESS_EXIT_CODE = 0
ERROR_EXIT_CODE = 1
PASSTHROUGH_EXIT_CODE = 23

SOCKET_TIMEOUT_SECONDS = 1
CERTUTIL_TIMEOUT_SECONDS = 10
ENTRYPOINT_TIMEOUT_SECONDS = 15


def run_entrypoint(
    tmp_path: Path,
    overrides: dict[str, str],
    command: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    "execute docker entrypoint with environment overrides"

    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "LOOPHOLE_ENABLED": ENABLED_LOOPHOLE,
        "LOOPHOLE_CA_CERT": str(tmp_path / "absent.crt"),
        "LOOPHOLE_CA_CERT_B64": "",
        "LOOPHOLE_TARGET_IP": DEFAULT_TARGET_IP,
        "LOOPHOLE_HTTP_PORT": DEFAULT_HTTP_PORT,
        "LOOPHOLE_HTTPS_PORT": DEFAULT_HTTPS_PORT,
        **overrides,
    }
    target_command = command or ["sh", "-c", f"exit {PASSTHROUGH_EXIT_CODE}"]

    return subprocess.run(
        [ENTRYPOINT, *target_command],
        env=env,
        capture_output=True,
        text=True,
        timeout=ENTRYPOINT_TIMEOUT_SECONDS,
    )


def read_ca_certutil_entry(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["certutil", "-d", f"sql:{tmp_path / '.pki' / 'nssdb'}", "-L", "-n", CA_NICKNAME],
        capture_output=True,
        text=True,
        timeout=CERTUTIL_TIMEOUT_SECONDS,
    )


def test_disabled_preserves_command_status(tmp_path: Path) -> None:
    result = run_entrypoint(tmp_path, {"LOOPHOLE_ENABLED": DISABLED_LOOPHOLE})

    assert result.returncode == PASSTHROUGH_EXIT_CODE
    assert "skipping" in result.stdout


@pytest.mark.parametrize("address", [LOOPBACK_IPV4, "127.42.0.1", "::1"])
def test_loopback_override_bypasses_relay(tmp_path: Path, address: str) -> None:
    result = run_entrypoint(tmp_path, {"LOOPHOLE_TARGET_IP": address})

    assert result.returncode == PASSTHROUGH_EXIT_CODE


@pytest.mark.parametrize("address", [f"{DEFAULT_TARGET_IP}\nfrontend injected", "not-an-ip"])
def test_invalid_address_stops_before_command(tmp_path: Path, address: str) -> None:
    result = run_entrypoint(tmp_path, {"LOOPHOLE_TARGET_IP": address})

    assert result.returncode == ERROR_EXIT_CODE
    assert "Invalid host IP" in result.stderr


@pytest.mark.parametrize("port", ["0", "65536", DEFAULT_HTTPS_PORT, "80\nmalicious", "-1"])
def test_invalid_or_conflicting_ports(tmp_path: Path, port: str) -> None:
    result = run_entrypoint(tmp_path, {"LOOPHOLE_HTTP_PORT": port})

    assert result.returncode == ERROR_EXIT_CODE


def test_ca_is_imported_even_when_relay_disabled(tmp_path: Path) -> None:
    result = run_entrypoint(
        tmp_path,
        {
            "LOOPHOLE_ENABLED": DISABLED_LOOPHOLE,
            "LOOPHOLE_CA_CERT": os.environ["LOOPHOLE_CA_CERT"],
        },
    )

    assert result.returncode == PASSTHROUGH_EXIT_CODE, result.stderr

    trust = read_ca_certutil_entry(tmp_path)

    assert trust.returncode == SUCCESS_EXIT_CODE, trust.stderr


def test_base64_ca_is_imported_even_when_relay_disabled(tmp_path: Path) -> None:
    cert = Path(os.environ["LOOPHOLE_CA_CERT"]).read_bytes()

    result = run_entrypoint(
        tmp_path,
        {
            "LOOPHOLE_ENABLED": DISABLED_LOOPHOLE,
            "LOOPHOLE_CA_CERT_B64": base64.b64encode(cert).decode("ascii"),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode == PASSTHROUGH_EXIT_CODE, result.stderr

    trust = read_ca_certutil_entry(tmp_path)

    assert trust.returncode == SUCCESS_EXIT_CODE, trust.stderr
    assert not list(tmp_path.glob("tmp.*"))


def test_invalid_base64_ca_stops_before_command(tmp_path: Path) -> None:
    result = run_entrypoint(
        tmp_path,
        {
            "LOOPHOLE_ENABLED": DISABLED_LOOPHOLE,
            "LOOPHOLE_CA_CERT_B64": "not-base64",
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode not in (SUCCESS_EXIT_CODE, PASSTHROUGH_EXIT_CODE)
    assert "LOOPHOLE_CA_CERT_B64" in result.stderr
    assert not list(tmp_path.glob("tmp.*"))


def test_bad_ca_stops_before_command(tmp_path: Path) -> None:
    cert = tmp_path / "broken.crt"
    cert.write_text("not a certificate")

    result = run_entrypoint(tmp_path, {"LOOPHOLE_CA_CERT": str(cert)})

    assert result.returncode not in (SUCCESS_EXIT_CODE, PASSTHROUGH_EXIT_CODE)


def test_conflicting_listener_stops_before_command(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind((LOOPBACK_IPV4, 0))
        listener.listen()
        port = listener.getsockname()[1]

        result = run_entrypoint(tmp_path, {"LOOPHOLE_HTTP_PORT": str(port)})

    assert result.returncode not in (SUCCESS_EXIT_CODE, PASSTHROUGH_EXIT_CODE)
    assert "cannot bind" in result.stderr.lower()


def test_privileged_listeners_are_ready_before_command(tmp_path: Path) -> None:
    # run an immediate connection check as the command, with no readiness polling
    code = (
        "import socket; "
        f"socket.create_connection(('{LOOPBACK_IPV4}', {int(DEFAULT_HTTP_PORT)}), timeout={SOCKET_TIMEOUT_SECONDS}).close(); "
        f"socket.create_connection(('{LOOPBACK_IPV4}', {int(DEFAULT_HTTPS_PORT)}), timeout={SOCKET_TIMEOUT_SECONDS}).close()"
    )

    result = run_entrypoint(tmp_path, {}, [sys.executable, "-c", code])

    assert result.returncode == SUCCESS_EXIT_CODE, result.stderr
