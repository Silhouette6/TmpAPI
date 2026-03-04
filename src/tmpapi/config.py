from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

_DEFAULT_CONFIG_PATHS = [
    BASE_DIR / "config.yaml",
    BASE_DIR / "config.yml",
]


# ── Settings models ─────────────────────────────────────────

class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8686
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class BrowserSettings(BaseModel):
    headless: bool = True
    channel: Literal["chrome", "msedge", "auto"] = "auto"


class ProviderSettings(BaseModel):
    name: str = "deepseek"
    profiles_dir: str = "profiles"


class DeepSeekSettings(BaseModel):
    chat_url: str = "https://chat.deepseek.com"
    login_url: str = "https://chat.deepseek.com/sign_in"
    new_chat_every_request: bool = True
    poll_interval: float = 0.4
    response_start_timeout: float = 120
    idle_timeout: float = 8
    min_generation_time: float = 3
    typing_delay_min: float = 0.035   # 每字符最小延迟（秒）
    typing_delay_max: float = 0.080   # 每字符最大延迟（秒）
    typing_burst_extra: float = 0.25  # 思考停顿额外最大延迟（秒）


class ChatGLMSettings(BaseModel):
    chat_url: str = "https://chatglm.cn/main/alltoolsdetail"
    login_url: str = "https://chatglm.cn"
    new_chat_every_request: bool = False
    poll_interval: float = 0.4
    response_start_timeout: float = 120
    idle_timeout: float = 3
    min_generation_time: float = 3
    typing_delay_min: float = 0.035   # 每字符最小延迟（秒）
    typing_delay_max: float = 0.080   # 每字符最大延迟（秒）
    typing_burst_extra: float = 0.25  # 思考停顿额外最大延迟（秒）


class DoubaoSettings(BaseModel):
    chat_url: str = "https://www.doubao.com/chat/"
    login_url: str = "https://www.doubao.com"
    new_chat_every_request: bool = False
    poll_interval: float = 0.4
    response_start_timeout: float = 120
    idle_timeout: float = 3
    min_generation_time: float = 3
    typing_delay_min: float = 0.035
    typing_delay_max: float = 0.080
    typing_burst_extra: float = 0.25


class Settings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    deepseek: DeepSeekSettings = Field(default_factory=DeepSeekSettings)
    chatglm: ChatGLMSettings = Field(default_factory=ChatGLMSettings)
    doubao: DoubaoSettings = Field(default_factory=DoubaoSettings)

    @property
    def profiles_dir(self) -> Path:
        p = Path(self.provider.profiles_dir)
        if not p.is_absolute():
            p = BASE_DIR / p
        return p

    @property
    def resolved_channel(self) -> str | None:
        """Return None when 'auto' so BrowserManager auto-detects."""
        return None if self.browser.channel == "auto" else self.browser.channel


# ── Loading ──────────────────────────────────────────────────

def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from a YAML file.

    Resolution order:
      1. Explicit *config_path* argument
      2. ``config.yaml`` / ``config.yml`` in project root
      3. Built-in defaults
    """
    paths_to_try: list[Path] = []
    if config_path:
        paths_to_try.append(Path(config_path))
    paths_to_try.extend(_DEFAULT_CONFIG_PATHS)

    for p in paths_to_try:
        if p.is_file():
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            logger.info("Loaded config from %s", p)
            return Settings(**raw)

    logger.info("No config file found, using defaults")
    return Settings()


# ── Singleton ────────────────────────────────────────────────

_settings: Settings | None = None


def get_settings(config_path: str | Path | None = None) -> Settings:
    """Return the global Settings singleton (lazy-loaded)."""
    global _settings
    if _settings is None:
        _settings = load_settings(config_path)
    return _settings


def reset_settings() -> None:
    """Force re-load on next ``get_settings()`` call."""
    global _settings
    _settings = None


# ── Provider registry ────────────────────────────────────────

PROVIDER_REGISTRY: dict[str, type] = {}


def register_provider(name: str, cls: type) -> None:
    PROVIDER_REGISTRY[name] = cls


def get_provider(name: str | None = None):
    """Instantiate a provider by name, using global settings."""
    settings = get_settings()
    provider_name = name or settings.provider.name
    if provider_name not in PROVIDER_REGISTRY:
        raise ValueError(
            f"Unknown provider '{provider_name}'. "
            f"Available: {list(PROVIDER_REGISTRY.keys())}"
        )
    profile_dir = settings.profiles_dir / provider_name
    return PROVIDER_REGISTRY[provider_name](profile_dir=profile_dir)


def _register_builtins() -> None:
    from tmpapi.providers.deepseek import DeepSeekProvider
    from tmpapi.providers.chatglm import ChatGLMProvider
    from tmpapi.providers.doubao import DoubaoProvider
    register_provider("deepseek", DeepSeekProvider)
    register_provider("chatglm", ChatGLMProvider)
    register_provider("doubao", DoubaoProvider)


_register_builtins()
