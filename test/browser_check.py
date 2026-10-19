"""Run inside the test image, against its default Playwright server."""
import os
from pathlib import Path
import socket
import time

from playwright.sync_api import Error, expect, sync_playwright
from python_hosts import Hosts, HostsEntry

HOSTNAME = "service.loophole.test"
SCREENSHOT = Path("/tmp/loophole-artifacts/service.png")


def main():
    hosts = Hosts(path="/etc/hosts")
    if hosts.exists(names=[HOSTNAME]):
        raise AssertionError(f"Refusing to overwrite an existing entry for {HOSTNAME}")
    try:
        hosts.add(
            [HostsEntry(entry_type="ipv4", address="127.0.0.1", names=[HOSTNAME])],
            allow_address_duplication=True,
        )
        hosts.write()
        assert socket.gethostbyname(HOSTNAME) == "127.0.0.1"
        SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        # A fresh container must not pass by finding a screenshot from a prior run.
        assert not SCREENSHOT.exists(), "Unexpected stale screenshot"
        with sync_playwright() as playwright:
            deadline = time.monotonic() + 30
            while True:
                try:
                    browser = playwright.chromium.connect("ws://127.0.0.1:3000", timeout=2000)
                    break
                except Error:
                    if time.monotonic() >= deadline:
                        raise
                    # Retry server readiness, not relay readiness (HAProxy binds synchronously).
                    time.sleep(0.2)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                response = page.goto(os.environ["TEST_URL"], timeout=15000)
                assert response is not None and response.status == 200, "Expected HTTP 200"
                page.screenshot(path=str(SCREENSHOT), full_page=True)
                assert SCREENSHOT.is_file(), "Screenshot was not created"
                assert SCREENSHOT.stat().st_size > 0, "Screenshot is empty"
                assert SCREENSHOT.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), "Invalid PNG"
                expect(page.locator("body")).to_contain_text(os.environ["TEST_EXPECTED_TEXT"])
                print(f"PASS: expected page text and nonempty screenshot ({SCREENSHOT.stat().st_size} bytes)", flush=True)
            finally:
                browser.close()
    finally:
        hosts.remove_all_matching(name=HOSTNAME)
        hosts.write()
        assert not Hosts(path="/etc/hosts").exists(names=[HOSTNAME]), "Hosts entry cleanup failed"
        print(f"Removed hosts entry for {HOSTNAME}", flush=True)


if __name__ == "__main__":
    main()
