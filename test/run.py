"""Linux/GitHub Actions integration runner. Requires Docker and Python 3 only."""
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import html
import os
import signal
import subprocess
import threading
import uuid

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "test-results" / "end-to-end"
HOSTNAME = "service.loophole.test"


def docker(*args, **kwargs):
    print("+ docker " + " ".join(args), flush=True)
    return subprocess.run(["docker", *args], cwd=ROOT, check=True, **kwargs)


class Service(BaseHTTPRequestHandler):
    def __init__(self, *args, expected_text, **kwargs):
        self.expected_text = expected_text
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.headers.get("Host") != f"{HOSTNAME}:{self.server.server_port}":
            self.send_error(400, "Unexpected Host header")
            return
        body = ("<!doctype html><html><head><title>Loophole integration</title></head>"
                "<body><h1>Playwright Loophole</h1><p>" + html.escape(self.expected_text)
                + "</p></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.successful_requests += 1


def interrupted(signum, _frame):
    # Raising lets finally blocks collect logs and remove the container/server.
    raise SystemExit(128 + signum)


def main():
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    run_id = uuid.uuid4().hex
    image = f"playwright-loophole:test-{run_id}"
    test_image = f"playwright-loophole:verification-{run_id}"
    name = f"loophole-e2e-{run_id}"
    expected_text = f"The host service was reached through playwright-loophole: {run_id}"
    artifacts = ARTIFACTS / run_id
    artifacts.mkdir(parents=True)
    version = os.environ.get("PLAYWRIGHT_VERSION", "v1.50.0-noble")
    # Build the actual image first, then add Python-only test dependencies.
    docker("build", "--build-arg", f"PLAYWRIGHT_VERSION={version}", "-t", image, ".")
    docker("build", "-f", "test/Dockerfile", "--build-arg", f"LOOPHOLE_IMAGE={image}", "-t", test_image, ".")

    service = ThreadingHTTPServer(("0.0.0.0", 0), partial(Service, expected_text=expected_text))
    service.successful_requests = 0
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    port = service.server_port
    # The HTTP listener and upstream port match; a random free host port avoids CI conflicts.
    try:
        docker("run", "--detach", "--name", name, "--shm-size=1g",
               "--add-host=host.docker.internal:host-gateway",
               "--env", f"LOOPHOLE_HTTP_PORT={port}",
               "--env", f"TEST_URL=http://{HOSTNAME}:{port}/",
               "--env", f"TEST_EXPECTED_TEXT={expected_text}", test_image)
        docker("exec", name, "/opt/verification/bin/python", "/opt/verification/browser_check.py")
        docker("cp", f"{name}:/tmp/loophole-artifacts/service.png", str(artifacts / "service.png"))
        screenshot = artifacts / "service.png"
        assert screenshot.is_file() and screenshot.stat().st_size > 0, "Exported screenshot is missing or empty"
        assert service.successful_requests > 0, "The host service did not receive a browser request"
        print(f"PASS: screenshot exported to {screenshot.relative_to(ROOT)}", flush=True)
    finally:
        try:
            # Capture diagnostics even if browser assertions fail.
            with (artifacts / "container.log").open("w") as log:
                subprocess.run(["docker", "logs", name], stdout=log, stderr=subprocess.STDOUT, check=False)
            subprocess.run(["docker", "cp", f"{name}:/tmp/loophole-artifacts/.", str(artifacts)], check=False)
        finally:
            try:
                subprocess.run(["docker", "rm", "--force", name], check=False)
            finally:
                service.shutdown()
                service.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    main()
