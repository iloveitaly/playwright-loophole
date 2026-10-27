import os
import socket

from playwright.sync_api import expect

LOOPBACK_IP = "127.0.0.1"
TEST_HOST = "service.loophole.test"
NAVIGATION_TIMEOUT_MS = 15_000
EXPECTED_STATUS = 200
SCREENSHOT_FILENAME = "service.png"
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
BODY_SELECTOR = "body"

CHROMIUM_CHANNEL = "chromium"
CHROME_POLICY_URL = "chrome://policy"
POLICY_TABLE_SELECTOR = "policy-table"
POLICY_ROW_SELECTOR = "policy-row"
QUIC_ALLOWED_POLICY = "QuicAllowed"
POLICY_VALUE_FALSE = "false"
POLICY_STATUS_OK = "OK"


def test_http_page_and_screenshot(page, artifacts, expected_text):
    assert socket.gethostbyname(TEST_HOST) == LOOPBACK_IP
    screenshot = artifacts / SCREENSHOT_FILENAME
    assert not screenshot.exists(), "unexpected stale screenshot"

    response = page.goto(os.environ["TEST_URL"], timeout=NAVIGATION_TIMEOUT_MS)
    page.screenshot(path=screenshot, full_page=True)

    assert response is not None
    assert response.status == EXPECTED_STATUS
    assert screenshot.is_file()
    assert screenshot.stat().st_size > 0
    assert screenshot.read_bytes().startswith(PNG_HEADER)
    expect(page.locator(BODY_SELECTOR)).to_contain_text(expected_text)


def test_chromium_trusts_ca_without_ignoring_https_errors(page, expected_text):
    # chromium resolves *.localhost internally; no hosts entry is needed here
    response = page.goto(os.environ["TEST_HTTPS_URL"], timeout=NAVIGATION_TIMEOUT_MS)

    assert response is not None
    assert response.status == EXPECTED_STATUS
    expect(page.locator(BODY_SELECTOR)).to_contain_text(expected_text)


def test_quic_policy_value_and_status(playwright):
    # full chromium has chrome://policy; the legacy headless shell does not
    browser = playwright.chromium.launch(channel=CHROMIUM_CHANNEL)
    try:
        page = browser.new_page()

        page.goto(CHROME_POLICY_URL)

        row = (
            page.locator(POLICY_TABLE_SELECTOR)
            .locator(POLICY_ROW_SELECTOR)
            .filter(has_text=QUIC_ALLOWED_POLICY)
        )
        expect(row).to_contain_text(POLICY_VALUE_FALSE)
        expect(row).to_contain_text(POLICY_STATUS_OK)
    finally:
        browser.close()
