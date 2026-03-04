from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

from tmpapi.browser.manager import BrowserManager
from tmpapi.config import get_settings
from tmpapi.providers._utils import human_type
from tmpapi.providers.base import ChatProvider

logger = logging.getLogger(__name__)

_MODELS = [
    "doubao",
]


class DoubaoProvider(ChatProvider):
    """RPA provider that drives www.doubao.com via Playwright."""

    name = "doubao"

    def __init__(self, profile_dir: str | Path) -> None:
        self.profile_dir = Path(profile_dir)
        self._browser: BrowserManager | None = None
        self._channel: str | None = None

    @property
    def chat_url(self) -> str:
        return get_settings().doubao.chat_url

    @property
    def _db_settings(self):
        return get_settings().doubao

    # ── lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        self._browser = BrowserManager(
            self.profile_dir, headless=True, channel=self._channel,
        )
        await self._browser.launch()

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None

    # ── login ────────────────────────────────────────────────────

    async def login(self) -> None:
        bm = BrowserManager(self.profile_dir, headless=False, channel=self._channel)
        ctx = await bm.launch()
        login_url = self._db_settings.login_url
        page = await bm.new_page(login_url)
        logger.info("Browser opened at %s — please log in manually.", login_url)
        print(
            "\n╔══════════════════════════════════════════════════╗\n"
            "║  浏览器已打开豆包 AI 登录页面                   ║\n"
            "║  请在浏览器中完成登录操作                       ║\n"
            "║  登录完成后关闭浏览器窗口即可保存会话           ║\n"
            "╚══════════════════════════════════════════════════╝\n"
        )
        try:
            while ctx.pages:
                await asyncio.sleep(1)
        except Exception:
            pass
        finally:
            await bm.close()
        print("登录会话已保存。")

    # ── models ───────────────────────────────────────────────────

    def available_models(self) -> list[str]:
        return list(_MODELS)

    # ── chat ─────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        model: str,
        **kwargs,
    ) -> AsyncIterator[str]:
        if self._browser is None:
            raise RuntimeError("Provider not started")

        page = await self._browser.get_or_create_page(self._db_settings.chat_url)

        if self._db_settings.new_chat_every_request:
            await self._start_new_chat(page)

        bubble_count_before = await self._count_response_bubbles(page)

        prompt = self._build_prompt(messages)
        await self._send_message(page, prompt)

        async for chunk in self._stream_response(page, bubble_count_before):
            yield chunk

    # ── internal helpers ─────────────────────────────────────────

    @staticmethod
    def _build_prompt(messages: list[dict]) -> str:
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"[System Instruction]\n{content}\n")
            elif role == "user":
                parts.append(content)
            elif role == "assistant":
                parts.append(f"[Previous Assistant Reply]\n{content}\n")
        return "\n".join(parts)

    def _input_locator(self, page):
        return page.locator("textarea.semi-input-textarea, textarea:visible, div[contenteditable='true']:visible").first

    async def _start_new_chat(self, page) -> None:
        chat_url = self._db_settings.chat_url
        try:
            await page.goto(chat_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            textarea = self._input_locator(page)
            await textarea.wait_for(state="visible", timeout=10000)
        except Exception:
            logger.warning("Failed to start new chat, retrying...")
            await page.goto(chat_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

    async def _send_message(self, page, text: str) -> None:
        textarea = self._input_locator(page)
        await textarea.wait_for(state="visible", timeout=15000)
        await textarea.click()
        await page.keyboard.press("Control+A")
        await asyncio.sleep(0.05)
        db = self._db_settings
        await human_type(
            page, text,
            delay_min=db.typing_delay_min,
            delay_max=db.typing_delay_max,
            burst_extra=db.typing_burst_extra,
        )
        await asyncio.sleep(0.3)

        sent = False

        # Strategy 1: JS — look for a send button with SVG icon
        try:
            sent = await page.evaluate("""
                () => {
                    const candidates = document.querySelectorAll(
                        '[role="button"], button, [class*="btn"], [class*="send"], [class*="submit"]'
                    );
                    for (const el of candidates) {
                        const rect = el.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) continue;
                        if (rect.width > 80 || rect.height > 80) continue;
                        const style = window.getComputedStyle(el);
                        const bg = style.backgroundColor;
                        if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                            const svg = el.querySelector('svg');
                            if (svg) {
                                el.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }
            """)
        except Exception:
            pass

        # Strategy 2: common doubao.com selectors
        if not sent:
            for selector in [
                '[class*="send-btn"]',
                '[class*="submit-btn"]',
                '[data-testid="send_button"]',
                'div[class*="chat-input"] button',
                'div[class*="input-area"] button',
                'textarea ~ button',
                'textarea + div button',
            ]:
                try:
                    btn = page.locator(selector).last
                    if await btn.is_visible(timeout=500):
                        await btn.click()
                        sent = True
                        break
                except Exception:
                    continue

        # Strategy 3: Enter key
        if not sent:
            logger.debug("Send button not found, trying Enter key")
            await textarea.press("Enter")

        await asyncio.sleep(0.3)
        logger.debug("Message sent (button_clicked=%s)", sent)

    async def _stream_response(
        self, page, bubble_offset: int = 0,
    ) -> AsyncIterator[str]:
        db = self._db_settings
        poll_interval = db.poll_interval
        start_timeout = db.response_start_timeout
        idle_timeout = db.idle_timeout
        min_gen_time = db.min_generation_time

        collected = ""
        idle_elapsed = 0.0
        total_elapsed = 0.0
        started = False

        max_iterations = int((start_timeout + idle_timeout + 300) / poll_interval)

        for _ in range(max_iterations):
            await asyncio.sleep(poll_interval)
            total_elapsed += poll_interval

            current_text = await self._get_response_text_at(page, bubble_offset)

            if current_text and len(current_text) > len(collected):
                new_part = current_text[len(collected):]
                collected = current_text
                idle_elapsed = 0.0
                if not started:
                    started = True
                    logger.debug("Response started")
                yield new_part
            else:
                idle_elapsed += poll_interval

                if not started:
                    if idle_elapsed >= start_timeout:
                        logger.warning("Timed out waiting for response to start")
                        break
                    continue

                if idle_elapsed < idle_timeout:
                    continue
                if total_elapsed < min_gen_time:
                    continue

                if await self._is_input_ready(page):
                    final = await self._get_response_text_at(page, bubble_offset)
                    if final and len(final) > len(collected):
                        yield final[len(collected):]
                    logger.debug(
                        "Generation complete (%d chars, %.1fs)",
                        len(collected), total_elapsed,
                    )
                    break

    # ── DOM helpers ──────────────────────────────────────────────

    @staticmethod
    async def _count_response_bubbles(page) -> int:
        try:
            return await page.evaluate("""
                () => document.querySelectorAll(
                    'div[class*="flow-markdown-body"]'
                ).length
            """)
        except Exception:
            return 0

    @staticmethod
    async def _get_response_text_at(page, index: int) -> str:
        try:
            result = await page.evaluate("""
                (idx) => {
                    const bubbles = document.querySelectorAll(
                        'div[class*="flow-markdown-body"]'
                    );
                    if (idx >= bubbles.length) return '';
                    return bubbles[idx].innerText || '';
                }
            """, index)
            return result or ""
        except Exception:
            return ""

    @staticmethod
    async def _is_input_ready(page) -> bool:
        try:
            return await page.evaluate("""
                () => {
                    const ta = document.querySelector('textarea.semi-input-textarea');
                    if (ta) return !ta.disabled && !ta.readOnly;
                    return false;
                }
            """)
        except Exception:
            return True
