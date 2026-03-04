from __future__ import annotations

import logging
import shutil
from pathlib import Path

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

_stealth = Stealth()

_DEFAULT_VIEWPORT = {"width": 1280, "height": 900}

# channel 优先级: chrome -> msedge -> 不指定 (回退到 Playwright 内置 chromium)
_CHANNEL_PRIORITY = ["chrome", "msedge"]


def _detect_channel() -> str | None:
    """Auto-detect a locally installed Chromium-based browser."""
    for ch in _CHANNEL_PRIORITY:
        # Playwright accepts "chrome" / "msedge" as channel names and resolves
        # the executable path internally. We do a quick shutil.which check for
        # common executable names so we can log which one we picked.
        exe_names = {
            "chrome": ["chrome", "google-chrome", "google-chrome-stable"],
            "msedge": ["msedge", "microsoft-edge"],
        }
        for exe in exe_names.get(ch, []):
            if shutil.which(exe):
                return ch
    # On Windows, shutil.which may not find them because they live in
    # Program Files. Playwright itself knows how to find them, so we
    # optimistically try msedge (ships with every Windows 10/11).
    import platform
    if platform.system() == "Windows":
        return "msedge"
    return None


class BrowserManager:
    """Manages a Playwright persistent browser context.

    Uses the system-installed Chrome or Edge by default so there is
    no need to download Playwright's bundled Chromium.

    Parameters
    ----------
    profile_dir:
        Directory used to persist cookies, localStorage, etc.
    headless:
        Whether to launch the browser without a visible window.
    channel:
        Browser channel to use ("chrome", "msedge", or None for auto-detect).
    """

    def __init__(
        self,
        profile_dir: str | Path,
        *,
        headless: bool = True,
        channel: str | None = None,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self.channel = channel or _detect_channel()

        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None

    # ── lifecycle ────────────────────────────────────────────────

    async def launch(self) -> BrowserContext:
        """Start Playwright and return a persistent browser context."""
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        self._pw = await async_playwright().start()
        launch_kwargs: dict = dict(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            viewport=_DEFAULT_VIEWPORT,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )
        if self.channel:
            launch_kwargs["channel"] = self.channel

        self._context = await self._pw.chromium.launch_persistent_context(
            **launch_kwargs,
        )
        logger.info(
            "Browser launched (channel=%s, headless=%s, profile=%s)",
            self.channel or "bundled-chromium",
            self.headless,
            self.profile_dir,
        )
        return self._context

    async def close(self) -> None:
        """Gracefully close the browser and Playwright."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._pw:
            await self._pw.stop()
            self._pw = None
        logger.info("Browser closed")

    # ── helpers ──────────────────────────────────────────────────

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser not launched yet – call launch() first")
        return self._context

    async def new_page(self, url: str | None = None) -> Page:
        """Create a new page, apply stealth, and optionally navigate."""
        page = await self.context.new_page()
        await _stealth.apply_stealth_async(page)
        if url:
            await page.goto(url, wait_until="domcontentloaded")
        return page

    async def get_or_create_page(self, url: str | None = None) -> Page:
        """Reuse the first existing page or create a new one."""
        pages = self.context.pages
        if pages:
            page = pages[0]
            await _stealth.apply_stealth_async(page)
            if url and not page.url.startswith(url.rstrip("/")):
                await page.goto(url, wait_until="domcontentloaded")
            return page
        return await self.new_page(url)
