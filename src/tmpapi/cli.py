from __future__ import annotations

import asyncio
import logging

import click
import uvicorn

from tmpapi.config import PROVIDER_REGISTRY, get_provider, get_settings


@click.group()
@click.option(
    "--config", "config_path", default=None, type=click.Path(),
    help="配置文件路径 (默认读取项目根目录 config.yaml)",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default=None,
    help="日志等级 (覆盖配置文件)",
)
@click.pass_context
def cli(ctx: click.Context, config_path: str | None, log_level: str | None) -> None:
    """TmpAPI — 浏览器 RPA 伪装的 OpenAI 格式 API"""
    from tmpapi.config import reset_settings
    if config_path:
        reset_settings()

    settings = get_settings(config_path)

    if log_level:
        settings.server.log_level = log_level.upper()

    logging.basicConfig(
        level=getattr(logging, settings.server.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj["settings"] = settings


@cli.command()
@click.option("--provider", default=None, help="要登录的模型提供商 (覆盖配置文件)")
@click.option(
    "--channel",
    type=click.Choice(["chrome", "msedge", "auto"], case_sensitive=False),
    default=None,
    help="浏览器类型 (覆盖配置文件)",
)
@click.pass_context
def login(ctx: click.Context, provider: str | None, channel: str | None) -> None:
    """打开浏览器让用户手动登录，保存会话 profile。"""
    settings = ctx.obj["settings"]

    if channel:
        settings.browser.channel = channel

    p = get_provider(provider)
    p._channel = settings.resolved_channel
    asyncio.run(p.login())


@cli.command()
@click.option("--provider", default=None, help="使用的模型提供商 (覆盖配置文件)")
@click.option("--host", default=None, help="监听地址 (覆盖配置文件)")
@click.option("--port", default=None, type=int, help="监听端口 (覆盖配置文件)")
@click.option("--headless/--no-headless", default=None, help="是否无头模式 (覆盖配置文件)")
@click.option(
    "--channel",
    type=click.Choice(["chrome", "msedge", "auto"], case_sensitive=False),
    default=None,
    help="浏览器类型 (覆盖配置文件)",
)
@click.pass_context
def server(
    ctx: click.Context,
    provider: str | None,
    host: str | None,
    port: int | None,
    headless: bool | None,
    channel: str | None,
) -> None:
    """启动 OpenAI 兼容的 API 服务器。"""
    settings = ctx.obj["settings"]

    # CLI overrides
    if host is not None:
        settings.server.host = host
    if port is not None:
        settings.server.port = port
    if headless is not None:
        settings.browser.headless = headless
    if channel is not None:
        settings.browser.channel = channel

    async def _run() -> None:
        p = get_provider(provider)
        from tmpapi.browser.manager import BrowserManager

        p._browser = BrowserManager(
            p.profile_dir,
            headless=settings.browser.headless,
            channel=settings.resolved_channel,
        )
        await p._browser.launch()
        await p._browser.get_or_create_page(p.chat_url)

        from tmpapi.server import create_app

        app = create_app(p)

        config = uvicorn.Config(
            app,
            host=settings.server.host,
            port=settings.server.port,
            log_level=settings.server.log_level.lower(),
        )
        server = uvicorn.Server(config)

        click.echo(f"\n  TmpAPI 服务已启动: http://{settings.server.host}:{settings.server.port}")
        click.echo(f"  Provider: {provider or settings.provider.name}")
        click.echo(f"  浏览器: {p._browser.channel or 'auto'}")
        click.echo(f"  Headless: {settings.browser.headless}")
        click.echo(f"  可用模型: {p.available_models()}")
        click.echo(f"  OpenAI base_url: http://localhost:{settings.server.port}/v1\n")

        try:
            await server.serve()
        finally:
            await p.stop()

    asyncio.run(_run())
