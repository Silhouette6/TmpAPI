from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class ChatProvider(ABC):
    """Abstract base class for all chat model providers.

    To add a new provider, subclass this and implement every abstract method.
    """

    name: str  # e.g. "deepseek", "chatglm", …

    @property
    @abstractmethod
    def chat_url(self) -> str:
        """Provider 主聊天页面 URL，用于初始化时导航。"""

    @abstractmethod
    async def start(self) -> None:
        """Initialise browser / resources needed for this provider."""

    @abstractmethod
    async def stop(self) -> None:
        """Release browser / resources."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Send *messages* and yield assistant reply text incrementally."""

    @abstractmethod
    async def login(self) -> None:
        """Open a **visible** browser so the user can log in manually.

        The implementation should block until the user closes the browser or
        signals that login is complete.  The browser profile must be persisted
        so that subsequent ``start()`` calls reuse the session.
        """

    @abstractmethod
    def available_models(self) -> list[str]:
        """Return the list of model identifiers this provider exposes."""
