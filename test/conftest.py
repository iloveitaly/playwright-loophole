import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import Error, sync_playwright

ARTIFACTS_DIR = Path("/tmp/loophole-artifacts")
CDP_URL = "ws://127.0.0.1:3000"
TIMEOUT_MS = 2_000
DEADLINE_SECONDS = 30
RETRY_INTERVAL_SECONDS = 0.2
VIEWPORT_WIDTH = 1_280
VIEWPORT_HEIGHT = 720
EXPECTED_TEXT_ENV_VAR = "TEST_EXPECTED_TEXT"


@pytest.fixture(scope="session")
def artifacts():
    ARTIFACTS_DIR.mkdir(exist_ok=True)

    return ARTIFACTS_DIR


@pytest.fixture(scope="session")
def playwright():
    with sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="session")
def browser(playwright):
    deadline = time.monotonic() + DEADLINE_SECONDS

    while True:
        try:
            instance = playwright.chromium.connect(CDP_URL, timeout=TIMEOUT_MS)
            break
        except Error:
            if time.monotonic() >= deadline:
                raise

            # retry the server, not haproxy readiness (listeners bind synchronously)
            time.sleep(RETRY_INTERVAL_SECONDS)

    yield instance

    instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})

    yield context.new_page()

    context.close()


@pytest.fixture(scope="session")
def expected_text():
    return os.environ[EXPECTED_TEXT_ENV_VAR]
