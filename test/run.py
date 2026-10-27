"Build the image and run the Python suite against host HTTP/TLS services"

import html
import ipaddress
import os
import signal
import ssl
import subprocess
import threading
import tomllib
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "test-results" / "end-to-end"
CONTAINER_ARTIFACTS = "/tmp/loophole-artifacts"

HOSTNAME = "service.loophole.test"
TLS_HOSTNAME = "fixture.localhost"
ROOT_CA_COMMON_NAME = "Loophole test root"
LOOPBACK_IP = "127.0.0.1"

BIND_ALL_HOST = "0.0.0.0"
EPHEMERAL_PORT = 0

RSA_KEY_SIZE = 2_048
RSA_PUBLIC_EXPONENT = 65_537
CERT_BACKDATE_MINUTES = 5
CERT_VALIDITY_DAYS = 1

THREAD_JOIN_TIMEOUT_SECONDS = 5
SIGNAL_EXIT_OFFSET = 128

DEFAULT_PLAYWRIGHT_VERSION = "v1.50.0-noble"
CONTAINER_SHM_SIZE = "1g"
HOST_GATEWAY = "host.docker.internal:host-gateway"
CONTAINER_CA_CERT_PATH = "/usr/local/share/ca-certificates/localias.crt"

ROOT_HOME = "/root"
PWUSER_HOME = "/home/pwuser"

TEST_USERS = ("root", "pwuser")
UV_RUN = ("uv", "run", "--no-sync")


def docker(*args: str, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    "run a docker command anchored to the project root"

    print("+ docker " + " ".join(args), flush=True)
    return subprocess.run(["docker", *args], cwd=ROOT, check=True, **kwargs)


def generate_rsa_private_key() -> rsa.RSAPrivateKey:
    "generate a private rsa key for testing certificates"

    return rsa.generate_private_key(
        public_exponent=RSA_PUBLIC_EXPONENT,
        key_size=RSA_KEY_SIZE,
    )


def build_root_certificate(
    root_key: rsa.RSAPrivateKey,
    start: datetime,
    expiry: datetime,
) -> x509.Certificate:
    "build a self-signed root ca certificate"

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ROOT_CA_COMMON_NAME)])
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(expiry)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(root_key, hashes.SHA256())
    )


def build_leaf_certificate(
    leaf_key: rsa.RSAPrivateKey,
    issuer_name: x509.Name,
    signing_key: rsa.RSAPrivateKey,
    start: datetime,
    expiry: datetime,
) -> x509.Certificate:
    "build a leaf certificate signed by the root ca"

    return (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, TLS_HOSTNAME)]))
        .issuer_name(issuer_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(expiry)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(HOSTNAME),
                    x509.DNSName(TLS_HOSTNAME),
                    x509.IPAddress(ipaddress.ip_address(LOOPBACK_IP)),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(signing_key, hashes.SHA256())
    )


def write_certificate_files(
    directory: Path,
    root: x509.Certificate,
    leaf: x509.Certificate,
    leaf_key: rsa.RSAPrivateKey,
) -> tuple[Path, Path, Path]:
    "write ca and leaf certificate files to disk"

    ca = directory / "ca.crt"
    cert = directory / "leaf.crt"
    key = directory / "leaf.key"

    ca.write_bytes(root.public_bytes(serialization.Encoding.PEM))
    cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    return ca, cert, key


def certificate_files(directory: Path) -> tuple[Path, Path, Path]:
    "create a root ca and signed leaf certificate in the specified directory"

    root_key = generate_rsa_private_key()
    leaf_key = generate_rsa_private_key()

    start = datetime.now(UTC) - timedelta(minutes=CERT_BACKDATE_MINUTES)
    expiry = start + timedelta(days=CERT_VALIDITY_DAYS)

    root = build_root_certificate(root_key, start, expiry)
    leaf = build_leaf_certificate(leaf_key, root.subject, root_key, start, expiry)

    return write_certificate_files(directory, root, leaf, leaf_key)


def render_html_body(expected_text: str) -> bytes:
    "render integration response html containing the expected text"

    return (
        "<!doctype html><html><head><title>Loophole integration</title></head>"
        f"<body><h1>Playwright Loophole</h1><p>{html.escape(expected_text)}</p></body></html>"
    ).encode()


class Service(BaseHTTPRequestHandler):
    "fixture http server validating requests and tracking counts"

    def __init__(self, *args, expected_text: str, **kwargs):
        self.expected_text = expected_text
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        "handle get requests and validate hostname and sni"

        host = self.headers.get("Host")
        valid_hosts = {
            f"{HOSTNAME}:{self.server.server_port}",
            f"{TLS_HOSTNAME}:{self.server.server_port}",
        }
        if host not in valid_hosts:
            self.send_error(HTTPStatus.BAD_REQUEST, "Unexpected Host header")
            return

        if (
            isinstance(self.connection, ssl.SSLSocket)
            and getattr(self.connection, "test_sni", None) != host.rsplit(":", 1)[0]
        ):
            self.send_error(HTTPStatus.BAD_REQUEST, "SNI was not preserved")
            return

        body = render_html_body(self.expected_text)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        self.wfile.write(body)

        with self.server.request_lock:
            self.server.successful_requests += 1


def interrupted(signum: int, _frame: object) -> None:
    "exit immediately when interrupted by a signal"

    raise SystemExit(SIGNAL_EXIT_OFFSET + signum)


def start_test_container(
    name: str,
    user: str,
    test_image: str,
    ca_path: Path,
    http_port: int,
    https_port: int,
    expected_text: str,
) -> None:
    "launch the test container with bound certificates and configuration"

    home = ROOT_HOME if user == "root" else PWUSER_HOME

    docker(
        "run",
        "--detach",
        "--name",
        name,
        "--user",
        user,
        f"--shm-size={CONTAINER_SHM_SIZE}",
        f"--add-host={HOST_GATEWAY}",
        "--mount",
        f"type=bind,source={ca_path},target={CONTAINER_CA_CERT_PATH},readonly",
        "--env",
        f"HOME={home}",
        "--env",
        f"LOOPHOLE_HTTP_PORT={http_port}",
        "--env",
        f"LOOPHOLE_HTTPS_PORT={https_port}",
        "--env",
        f"LOOPHOLE_CA_CERT={CONTAINER_CA_CERT_PATH}",
        "--env",
        f"TEST_URL=http://{HOSTNAME}:{http_port}/",
        "--env",
        f"TEST_HTTPS_URL=https://{TLS_HOSTNAME}:{https_port}/",
        "--env",
        f"TEST_EXPECTED_TEXT={expected_text}",
        test_image,
    )


def add_hosts_entry(name: str) -> None:
    "add loopback hosts entry inside the container"

    # hosts tool requires root privileges even during non-root test runs
    docker("exec", "--user", "root", name, *UV_RUN, "python", "test/hosts.py", "add")


def remove_hosts_entry(name: str) -> None:
    "remove loopback hosts entry inside the container"

    # hosts tool requires root privileges even during non-root test runs
    docker("exec", "--user", "root", name, *UV_RUN, "python", "test/hosts.py", "remove")


def run_pytest(name: str) -> None:
    "run the test suite inside the container"

    docker(
        "exec",
        name,
        *UV_RUN,
        "pytest",
        "-v",
        "--tb=short",
        f"--junitxml={CONTAINER_ARTIFACTS}/pytest.xml",
    )


def copy_and_verify_screenshot(name: str, artifacts: Path, user: str) -> None:
    "copy test screenshot from container and verify it is non-empty"

    screenshot = artifacts / "service.png"
    docker("cp", f"{name}:{CONTAINER_ARTIFACTS}/service.png", str(screenshot))

    assert screenshot.is_file() and screenshot.stat().st_size > 0
    print(f"PASS ({user}): screenshot exported to {screenshot.relative_to(ROOT)}", flush=True)


def collect_container_artifacts(name: str, artifacts: Path) -> None:
    "copy container logs and artifacts to host"

    log_path = artifacts / "container.log"
    logs = subprocess.run(
        ["docker", "logs", name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.write_bytes(logs.stdout)

    subprocess.run(
        ["docker", "cp", f"{name}:{CONTAINER_ARTIFACTS}/.", str(artifacts)],
        check=False,
    )


def remove_container(name: str) -> None:
    "forcibly remove container"

    subprocess.run(["docker", "rm", "--force", name], check=False)


def cleanup_container(name: str, artifacts: Path, created: bool) -> None:
    "clean up container resources and collect artifacts"

    try:
        if created:
            remove_hosts_entry(name)
    finally:
        try:
            collect_container_artifacts(name, artifacts)
        finally:
            remove_container(name)


def suite_for_user(
    test_image: str,
    run_id: str,
    user: str,
    ca: Path,
    http_port: int,
    https_port: int,
    expected_text: str,
) -> None:
    "run full integration test suite for a given user"

    name = f"loophole-e2e-{run_id}-{user}"
    artifacts = ARTIFACTS / run_id / user
    artifacts.mkdir(parents=True)
    created = False

    try:
        start_test_container(
            name=name,
            user=user,
            test_image=test_image,
            ca_path=ca,
            http_port=http_port,
            https_port=https_port,
            expected_text=expected_text,
        )
        created = True

        add_hosts_entry(name)
        run_pytest(name)
        copy_and_verify_screenshot(name, artifacts, user)
    finally:
        cleanup_container(name, artifacts, created)


def read_mise_tools() -> dict[str, str]:
    "read tool versions configured in mise.toml"

    return tomllib.loads((ROOT / "mise.toml").read_text())["tools"]


def build_test_images(run_id: str) -> str:
    "build or pull the base image and build the test verification image"

    supplied_image = os.environ.get("TEST_IMAGE")
    image = supplied_image or f"playwright-loophole:test-{run_id}"
    test_image = f"playwright-loophole:verification-{run_id}"
    version = os.environ.get("PLAYWRIGHT_VERSION", DEFAULT_PLAYWRIGHT_VERSION)

    if supplied_image:
        docker("pull", supplied_image)
    else:
        docker("build", "--build-arg", f"PLAYWRIGHT_VERSION={version}", "-t", image, ".")

    tools = read_mise_tools()
    docker(
        "build",
        "-f",
        "test/Dockerfile",
        "--build-arg",
        f"LOOPHOLE_IMAGE={image}",
        "--build-arg",
        f"UV_VERSION={tools['uv']}",
        "--build-arg",
        f"PYTHON_VERSION={tools['python']}",
        "-t",
        test_image,
        ".",
    )

    return test_image


def create_tls_context(cert: Path, key: Path) -> ssl.SSLContext:
    "create ssl context with certificates and sni recording"

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)

    def record_sni(connection: ssl.SSLSocket, name: str, _context: object) -> None:
        connection.test_sni = name

    context.set_servername_callback(record_sni)
    return context


def start_test_server(
    handler: partial,
    tls_context: ssl.SSLContext | None = None,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    "start a background threading http or https server"

    server = ThreadingHTTPServer((BIND_ALL_HOST, EPHEMERAL_PORT), handler)
    server.successful_requests = 0
    server.request_lock = threading.Lock()

    if tls_context:
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, thread


def stop_servers(
    servers: list[ThreadingHTTPServer],
    threads: list[threading.Thread],
) -> None:
    "shut down servers and wait for worker threads"

    for server in servers[: len(threads)]:
        server.shutdown()

    for server in servers:
        server.server_close()

    for thread in threads:
        thread.join(timeout=THREAD_JOIN_TIMEOUT_SECONDS)


@contextmanager
def run_fixture_servers(
    handler: partial,
    cert: Path,
    key: Path,
) -> Generator[list[ThreadingHTTPServer]]:
    "manage lifecycle of http and https fixture servers"

    tls_context = create_tls_context(cert, key)
    http_server, http_thread = start_test_server(handler)
    https_server, https_thread = start_test_server(handler, tls_context)

    servers = [http_server, https_server]
    threads = [http_thread, https_thread]

    try:
        yield servers
    finally:
        stop_servers(servers, threads)


def run_test_suites(
    test_image: str,
    run_id: str,
    ca: Path,
    http_port: int,
    https_port: int,
    expected_text: str,
) -> None:
    "run test suites for all configured users and report failures"

    failures: list[str] = []
    for user in TEST_USERS:
        try:
            suite_for_user(
                test_image=test_image,
                run_id=run_id,
                user=user,
                ca=ca,
                http_port=http_port,
                https_port=https_port,
                expected_text=expected_text,
            )
        except Exception as error:
            # record failures across all users to report all breakages at once
            failures.append(f"{user}: {error}")

    if failures:
        raise RuntimeError("Suite failures: " + "; ".join(failures))


def main() -> None:
    "entry point for executing end-to-end integration tests"

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    run_id = uuid.uuid4().hex
    test_image = build_test_images(run_id)

    expected_text = f"The host service was reached through playwright-loophole: {run_id}"
    handler = partial(Service, expected_text=expected_text)

    with TemporaryDirectory(prefix="loophole-ca-") as directory:
        ca, cert, key = certificate_files(Path(directory))

        with run_fixture_servers(handler, cert, key) as servers:
            run_test_suites(
                test_image=test_image,
                run_id=run_id,
                ca=ca,
                http_port=servers[0].server_port,
                https_port=servers[1].server_port,
                expected_text=expected_text,
            )

            assert all(server.successful_requests > 0 for server in servers)


if __name__ == "__main__":
    main()
