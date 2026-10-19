import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import Error, sync_playwright


@pytest.fixture(scope="session")
def artifacts():
    path = Path("/tmp/loophole-artifacts")
    path.mkdir(exist_ok=True)
    return path


@pytest.fixture(scope="session")
def playwright():
    with sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="session")
def browser(playwright):
    deadline = time.monotonic() + 30
    while True:
        try:
            instance = playwright.chromium.connect("ws://127.0.0.1:3000", timeout=2000)
            break
        except Error:
            if time.monotonic() >= deadline:
                raise
            # Retry the server, not HAProxy readiness (listeners bind synchronously).
            time.sleep(0.2)
    yield instance
    instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    yield context.new_page()
    context.close()


@pytest.fixture(scope="session")
def expected_text():
    return os.environ["TEST_EXPECTED_TEXT"]
