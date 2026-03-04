from __future__ import annotations

import asyncio
import random


async def human_type(
    page,
    text: str,
    delay_min: float = 0.035,
    delay_max: float = 0.080,
    burst_extra: float = 0.25,
) -> None:
    """Simulate human typing by sending one character at a time with randomised delays.

    Parameters
    ----------
    delay_min:
        Minimum per-character delay in seconds.
    delay_max:
        Maximum per-character delay in seconds.
    burst_extra:
        Maximum additional delay after punctuation or random "thinking" pauses.
    """
    pause_chars = set("，。！？；、,.!?;\n")

    for i, char in enumerate(text):
        if char == "\n":
            await page.keyboard.press("Shift+Enter")
        else:
            await page.keyboard.type(char)

        delay = random.uniform(delay_min, delay_max)

        if char in pause_chars:
            delay += random.uniform(burst_extra * 0.4, burst_extra)
        elif i > 0 and i % random.randint(20, 40) == 0:
            delay += random.uniform(burst_extra * 0.4, burst_extra)

        await asyncio.sleep(delay)
