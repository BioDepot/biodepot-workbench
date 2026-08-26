"""Browser interaction coverage for Workbench conversation management."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import pytest

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import Page, expect, sync_playwright
except ImportError:  # pragma: no cover - optional browser dependency.
    PlaywrightError = Exception  # type: ignore[assignment]
    Page = Any  # type: ignore[misc,assignment]
    expect = None  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(base_url: str, proc: subprocess.Popen[str]) -> None:
    deadline = time.time() + 30
    last_error: Exception | None = None
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout is not None else ""
            raise RuntimeError(f"Workbench server exited early: {output}")
        try:
            with urlopen(f"{base_url}/healthz", timeout=1.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Workbench server did not become ready: {last_error}")


@pytest.fixture(scope="module")
def conversation_server(tmp_path_factory: pytest.TempPathFactory) -> str:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    state_root = tmp_path_factory.mktemp("conversation-playwright")
    env = os.environ.copy()
    env["MORPHIC_AGENT_DB_PATH"] = str(state_root / "workbench.sqlite3")
    env["MORPHIC_AGENT_DISABLE_CONFIG_LLM"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "morphic_agent.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server(base_url, proc)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture(scope="module")
def browser() -> Any:
    if sync_playwright is None:
        pytest.skip("Playwright is not installed")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                yield browser
            finally:
                browser.close()
    except PlaywrightError as exc:
        pytest.skip(f"Playwright chromium is unavailable: {exc}")


@pytest.fixture()
def page(browser: Any, conversation_server: str) -> Page:
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.set_default_timeout(30_000)
    page.goto(conversation_server, wait_until="networkidle")
    return page


def test_conversation_create_resume_rename_fork_archive(page: Page):
    page.locator("#newConversationBtn").click()
    expect(page.locator("#activeConversationLabel")).to_have_text("New conversation")
    expect(page.locator(".conversation-item")).to_have_count(1)

    page.locator("#goal").fill("Draft a trimodal QC workflow")
    page.locator("#sendBtn").click()
    expect(page.locator("#status")).to_have_text("ready")
    expect(page.locator("#activeConversationLabel")).to_have_text("Draft a trimodal QC workflow")

    page.once("dialog", lambda dialog: dialog.accept("Trimodal tutorial"))
    page.locator("#renameConversationBtn").click()
    expect(page.locator("#activeConversationLabel")).to_have_text("Trimodal tutorial")

    page.reload(wait_until="networkidle")
    expect(page.locator("#activeConversationLabel")).to_have_text("Trimodal tutorial")
    expect(page.locator("#messages .msg.user")).to_contain_text("Draft a trimodal QC workflow")

    page.locator("#forkConversationBtn").click()
    expect(page.locator("#activeConversationLabel")).to_have_text("Copy of Trimodal tutorial")
    expect(page.locator(".conversation-item")).to_have_count(2)

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#archiveConversationBtn").click()
    expect(page.locator("#activeConversationLabel")).to_have_text("No active conversation")
    expect(page.locator(".conversation-item")).to_have_count(1)


def test_conversation_manager_fits_mobile_viewport(browser: Any, conversation_server: str):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(conversation_server, wait_until="networkidle")
        manager = page.locator(".conversation-manager")
        expect(manager).to_be_visible()
        box = manager.bounding_box()
        assert box is not None
        assert box["x"] >= 0
        assert box["x"] + box["width"] <= 390
        assert box["height"] >= 150
        manager.scroll_into_view_if_needed()
        expect(page.locator("#newConversationBtn")).to_be_visible()
        expect(page.locator("#conversationSearch")).to_be_visible()
    finally:
        page.close()
