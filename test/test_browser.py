import os
import socket

from playwright.sync_api import expect


def test_http_page_and_screenshot(page, artifacts, expected_text):
    assert socket.gethostbyname("service.loophole.test") == "127.0.0.1"
    response = page.goto(os.environ["TEST_URL"], timeout=15000)
    assert response is not None and response.status == 200
    screenshot = artifacts / "service.png"
    assert not screenshot.exists(), "Unexpected stale screenshot"
    page.screenshot(path=str(screenshot), full_page=True)
    assert screenshot.is_file()
    assert screenshot.stat().st_size > 0
    assert screenshot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    expect(page.locator("body")).to_contain_text(expected_text)


def test_chromium_trusts_ca_without_ignoring_https_errors(page, expected_text):
    # Chromium resolves *.localhost internally; no hosts entry is needed here.
    response = page.goto(os.environ["TEST_HTTPS_URL"], timeout=15000)
    assert response is not None and response.status == 200
    expect(page.locator("body")).to_contain_text(expected_text)


def test_quic_policy_value_and_status(playwright):
    # Full Chromium has chrome://policy; the legacy headless shell does not.
    browser = playwright.chromium.launch(channel="chromium")
    try:
        page = browser.new_page()
        page.goto("chrome://policy")
        row = page.locator("policy-table").locator("policy-row").filter(has_text="QuicAllowed")
        expect(row).to_contain_text("false")
        expect(row).to_contain_text("OK")
    finally:
        browser.close()
