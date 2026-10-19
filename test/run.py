"""Build the image and run the Python suite against host HTTP/TLS services."""

import html
import ipaddress
import os
import signal
import ssl
import subprocess
import threading
import tomllib
import uuid
from datetime import UTC, datetime, timedelta
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "test-results" / "end-to-end"
HOSTNAME = "service.loophole.test"
TLS_HOSTNAME = "fixture.localhost"
CONTAINER_ARTIFACTS = "/tmp/loophole-artifacts"


def docker(*args, **kwargs):
    print("+ docker " + " ".join(args), flush=True)
    return subprocess.run(["docker", *args], cwd=ROOT, check=True, **kwargs)


def certificate_files(directory):
    """Create a real root CA and signed leaf certificate, using Python tooling only."""
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Loophole test root")])
    start = datetime.now(UTC) - timedelta(minutes=5)
    root = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=1))
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
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, TLS_HOSTNAME)]))
        .issuer_name(name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(HOSTNAME),
                    x509.DNSName(TLS_HOSTNAME),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(root_key, hashes.SHA256())
    )
    ca, cert, key = (directory / filename for filename in ("ca.crt", "leaf.crt", "leaf.key"))
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


class Service(BaseHTTPRequestHandler):
    def __init__(self, *args, expected_text, **kwargs):
        self.expected_text = expected_text
        super().__init__(*args, **kwargs)

    def do_GET(self):
        host = self.headers.get("Host")
        if host not in {
            f"{HOSTNAME}:{self.server.server_port}",
            f"{TLS_HOSTNAME}:{self.server.server_port}",
        }:
            self.send_error(400, "Unexpected Host header")
            return
        if isinstance(self.connection, ssl.SSLSocket):
            expected_sni = host.rsplit(":", 1)[0]
            if getattr(self.connection, "test_sni", None) != expected_sni:
                self.send_error(400, "SNI was not preserved")
                return
        body = (
            "<!doctype html><html><head><title>Loophole integration</title></head>"
            "<body><h1>Playwright Loophole</h1><p>"
            + html.escape(self.expected_text)
            + "</p></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        with self.server.request_lock:
            self.server.successful_requests += 1


def interrupted(signum, _frame):
    raise SystemExit(128 + signum)


def suite_for_user(test_image, run_id, user, ca, http_port, https_port, expected_text):
    name = f"loophole-e2e-{run_id}-{user}"
    artifacts = ARTIFACTS / run_id / user
    artifacts.mkdir(parents=True)
    home = "/root" if user == "root" else "/home/pwuser"
    created = False
    uv = ["uv", "run", "--no-sync"]
    try:
        docker(
            "run",
            "--detach",
            "--name",
            name,
            "--user",
            user,
            "--shm-size=1g",
            "--add-host=host.docker.internal:host-gateway",
            "--mount",
            f"type=bind,source={ca},target=/usr/local/share/ca-certificates/localias.crt,readonly",
            "--env",
            f"HOME={home}",
            "--env",
            f"LOOPHOLE_HTTP_PORT={http_port}",
            "--env",
            f"LOOPHOLE_HTTPS_PORT={https_port}",
            "--env",
            "LOOPHOLE_CA_CERT=/usr/local/share/ca-certificates/localias.crt",
            "--env",
            f"TEST_URL=http://{HOSTNAME}:{http_port}/",
            "--env",
            f"TEST_HTTPS_URL=https://{TLS_HOSTNAME}:{https_port}/",
            "--env",
            f"TEST_EXPECTED_TEXT={expected_text}",
            test_image,
        )
        created = True
        # Only the hosts-management tool needs root, even in the pwuser test run.
        docker("exec", "--user", "root", name, *uv, "python", "test/hosts.py", "add")
        docker(
            "exec",
            name,
            *uv,
            "pytest",
            "-v",
            "--tb=short",
            f"--junitxml={CONTAINER_ARTIFACTS}/pytest.xml",
        )
        docker("cp", f"{name}:{CONTAINER_ARTIFACTS}/service.png", str(artifacts / "service.png"))
        screenshot = artifacts / "service.png"
        assert screenshot.is_file() and screenshot.stat().st_size > 0
        print(f"PASS ({user}): screenshot exported to {screenshot.relative_to(ROOT)}", flush=True)
    finally:
        try:
            if created:
                # Remove the hosts entry even if pytest fails, then verify removal.
                docker("exec", "--user", "root", name, *uv, "python", "test/hosts.py", "remove")
        finally:
            try:
                with (artifacts / "container.log").open("w") as log:
                    subprocess.run(
                        ["docker", "logs", name], stdout=log, stderr=subprocess.STDOUT, check=False
                    )
                subprocess.run(
                    ["docker", "cp", f"{name}:{CONTAINER_ARTIFACTS}/.", str(artifacts)], check=False
                )
            finally:
                subprocess.run(["docker", "rm", "--force", name], check=False)


def main():
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    run_id = uuid.uuid4().hex
    supplied_image = os.environ.get("TEST_IMAGE")
    image = supplied_image or f"playwright-loophole:test-{run_id}"
    test_image = f"playwright-loophole:verification-{run_id}"
    version = os.environ.get("PLAYWRIGHT_VERSION", "v1.50.0-noble")
    tools = tomllib.loads((ROOT / "mise.toml").read_text())["tools"]
    if supplied_image:
        docker("pull", supplied_image)
    else:
        docker("build", "--build-arg", f"PLAYWRIGHT_VERSION={version}", "-t", image, ".")
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
    expected_text = f"The host service was reached through playwright-loophole: {run_id}"
    handler = partial(Service, expected_text=expected_text)
    with TemporaryDirectory(prefix="loophole-ca-") as directory:
        ca, cert, key = certificate_files(Path(directory))
        servers = []
        threads = []
        try:
            for tls in (False, True):
                server = ThreadingHTTPServer(("0.0.0.0", 0), handler)
                servers.append(server)
                server.successful_requests = 0
                server.request_lock = threading.Lock()
                if tls:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.load_cert_chain(cert, key)

                    def record_sni(connection, name, _context):
                        connection.test_sni = name

                    context.set_servername_callback(record_sni)
                    server.socket = context.wrap_socket(server.socket, server_side=True)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                threads.append(thread)
            failures = []
            for user in ("root", "pwuser"):
                try:
                    suite_for_user(
                        test_image,
                        run_id,
                        user,
                        ca,
                        servers[0].server_port,
                        servers[1].server_port,
                        expected_text,
                    )
                except Exception as error:
                    failures.append(f"{user}: {error}")
            assert all(server.successful_requests > 0 for server in servers)
            if failures:
                raise RuntimeError("Suite failures: " + "; ".join(failures))
        finally:
            for server in servers[: len(threads)]:
                server.shutdown()
            for server in servers:
                server.server_close()
            for thread in threads:
                thread.join(timeout=5)


if __name__ == "__main__":
    main()
