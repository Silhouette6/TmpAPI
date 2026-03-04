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
    "deepseek-chat",
    "deepseek-reasoner",
]


class DeepSeekProvider(ChatProvider):
    """RPA provider that drives chat.deepseek.com via Playwright."""

    name = "deepseek"

    def __init__(self, profile_dir: str | Path) -> None:
        self.profile_dir = Path(profile_dir)
        self._browser: BrowserManager | None = None
        self._channel: str | None = None  # set externally by CLI

    @property
    def chat_url(self) -> str:
        return get_settings().deepseek.chat_url

    @property
    def _ds_settings(self):
        return get_settings().deepseek

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
        login_url = self._ds_settings.login_url
        page = await bm.new_page(login_url)
        logger.info("Browser opened at %s — please log in manually.", login_url)
        print(
            "\n╔══════════════════════════════════════════════════╗\n"
            "║  浏览器已打开 DeepSeek 登录页面                 ║\n"
            "║  请在浏览器中完成登录操作                       ║\n"
            "║  登录完成后关闭浏览器窗口即可保存会话           ║\n"
            "╚══════════════════════════════════════════════════╝\n"
        )
        # Wait until every page in the context is closed (user closes window)
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

        page = await self._browser.get_or_create_page(self._ds_settings.chat_url)

        is_reasoner = "reasoner" in model
        await self._ensure_model_mode(page, deep_think=is_reasoner)

        if self._ds_settings.new_chat_every_request:
            await self._start_new_chat(page)

        # Snapshot: count existing response bubbles so we only read the NEW one
        bubble_count_before = await self._count_response_bubbles(page)

        prompt = self._build_prompt(messages)
        await self._send_message(page, prompt)

        async for chunk in self._stream_response(page, bubble_count_before):
            yield chunk

    # ── internal helpers ─────────────────────────────────────────

    @staticmethod
    def _build_prompt(messages: list[dict]) -> str:
        """Collapse message list into a single prompt string.

        System messages are prepended as context instructions.
        Only the last user message is treated as the actual question.
        """
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

    async def _start_new_chat(self, page) -> None:
        """Start a fresh conversation to avoid context pollution."""
        # Most reliable approach: navigate directly to the chat root URL
        chat_url = self._ds_settings.chat_url
        try:
            await page.goto(chat_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            textarea = page.locator("textarea, div[contenteditable='true']").last
            await textarea.wait_for(state="visible", timeout=10000)
        except Exception:
            logger.warning("Failed to start new chat, retrying...")
            await page.goto(chat_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

    async def _ensure_model_mode(self, page, *, deep_think: bool) -> None:
        """Try toggling Deep Think mode on/off based on the requested model."""
        try:
            toggle = page.locator('div[class*="ds-chat-mode"]').first
            if not await toggle.is_visible(timeout=3000):
                return

            # Check current state — look for an active/selected indicator
            think_btn = page.locator('div[class*="think"], button:has-text("深度思考")').first
            if await think_btn.is_visible(timeout=2000):
                is_active = await think_btn.evaluate(
                    "(el) => el.classList.contains('active') || "
                    "el.getAttribute('aria-pressed') === 'true' || "
                    "el.closest('[class*=\"active\"]') !== null"
                )
                if deep_think and not is_active:
                    await think_btn.click()
                    await asyncio.sleep(0.5)
                elif not deep_think and is_active:
                    await think_btn.click()
                    await asyncio.sleep(0.5)
        except Exception:
            logger.debug("Could not toggle Deep Think mode — continuing with default")

    async def _send_message(self, page, text: str) -> None:
        """Type the prompt into the chat textarea and submit."""
        textarea = page.locator("textarea, div[contenteditable='true']").last
        await textarea.wait_for(state="visible", timeout=15000)
        await textarea.click()
        await page.keyboard.press("Control+A")
        await asyncio.sleep(0.05)
        ds = self._ds_settings
        await human_type(
            page, text,
            delay_min=ds.typing_delay_min,
            delay_max=ds.typing_delay_max,
            burst_extra=ds.typing_burst_extra,
        )
        await asyncio.sleep(0.3)

        # Try multiple strategies to click the send button
        sent = False

        # Strategy 1: find the send button via JS — look for the clickable
        # element near the bottom-right of the chat input area
        try:
            sent = await page.evaluate("""
                () => {
                    // DeepSeek's send button is typically an SVG arrow icon
                    // inside a circular container at the bottom-right of the input area
                    const candidates = document.querySelectorAll(
                        '[role="button"], button, [class*="btn"], [class*="send"], [class*="icon-button"]'
                    );
                    for (const el of candidates) {
                        const svg = el.querySelector('svg');
                        if (!svg) continue;
                        const rect = el.getBoundingClientRect();
                        // Send button is usually at the bottom-right, small and round
                        if (rect.width > 0 && rect.width < 60 && rect.height > 0 && rect.height < 60) {
                            const style = window.getComputedStyle(el);
                            const bg = style.backgroundColor;
                            // Active send button often has a colored background
                            if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
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

        # Strategy 2: find by the chat input area's sibling/parent structure
        if not sent:
            for selector in [
                'div[class*="chat-input"] [role="button"]',
                'div[class*="chat-input-actions"] [role="button"]',
                'textarea ~ div[role="button"]',
                'div[class*="icon-button"]:last-child',
            ]:
                try:
                    btn = page.locator(selector).last
                    if await btn.is_visible(timeout=500):
                        await btn.click()
                        sent = True
                        break
                except Exception:
                    continue

        # Strategy 3: keyboard shortcut — Ctrl+Enter sends on DeepSeek
        if not sent:
            logger.debug("Send button not found, trying Ctrl+Enter")
            await textarea.press("Control+Enter")

        await asyncio.sleep(0.3)
        logger.debug("Message sent (button_clicked=%s)", sent)

    async def _stream_response(
        self, page, bubble_offset: int = 0,
    ) -> AsyncIterator[str]:
        """Poll the page for new assistant text and yield incremental chunks.

        *bubble_offset* is the number of response bubbles that existed on the
        page **before** the current message was sent.  We only read the bubble
        at that index (the new one) so that old conversation history is ignored.
        """
        ds = self._ds_settings
        poll_interval = ds.poll_interval
        start_timeout = ds.response_start_timeout
        idle_timeout = ds.idle_timeout
        min_gen_time = ds.min_generation_time

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
        """Return the number of assistant response bubbles currently on the page."""
        try:
            return await page.evaluate("""
                () => document.querySelectorAll(
                    'div.ds-markdown, div[class*="markdown"]'
                ).length
            """)
        except Exception:
            return 0

    @staticmethod
    async def _get_response_text_at(page, index: int) -> str:
        """Extract the text of the response bubble at *index*."""
        try:
            result = await page.evaluate("""
                (idx) => {
                    const bubbles = document.querySelectorAll(
                        'div.ds-markdown, div[class*="markdown"]'
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
        """Check whether the chat textarea is editable (generation finished)."""
        try:
            return await page.evaluate("""
                () => {
                    const ta = document.querySelector('textarea');
                    if (!ta) return false;
                    return !ta.disabled && !ta.readOnly;
                }
            """)
        except Exception:
            return True
