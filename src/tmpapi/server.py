from __future__ import annotations

import json
import logging
import uuid
import time
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from tmpapi.providers.base import ChatProvider
from tmpapi.schemas import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    DeltaMessage,
    ModelInfo,
    ModelListResponse,
    StreamChoice,
    UsageInfo,
)

logger = logging.getLogger(__name__)


def create_app(provider: ChatProvider) -> FastAPI:
    app = FastAPI(title="TmpAPI", description="Browser-RPA OpenAI-compatible API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store provider on app state so routes can access it
    app.state.provider = provider

    # ── /v1/models ──────────────────────────────────────────────

    @app.get("/v1/models")
    async def list_models() -> ModelListResponse:
        models = [
            ModelInfo(id=m, owned_by=f"tmpapi-{provider.name}")
            for m in provider.available_models()
        ]
        return ModelListResponse(data=models)

    # ── /v1/chat/completions ────────────────────────────────────

    @app.post("/v1/chat/completions")
    async def chat_completions(request: ChatCompletionRequest):
        if request.model not in provider.available_models():
            raise HTTPException(
                status_code=400,
                detail=f"Model '{request.model}' not available. "
                f"Choose from: {provider.available_models()}",
            )

        messages = [m.model_dump() for m in request.messages]

        if request.stream:
            return EventSourceResponse(
                _stream_generator(provider, messages, request.model),
                media_type="text/event-stream",
            )

        # Non-streaming: collect all chunks into a single response
        full_text = ""
        async for chunk in provider.chat(messages, request.model):
            full_text += chunk

        return ChatCompletionResponse(
            model=request.model,
            choices=[
                Choice(message=ChoiceMessage(content=full_text)),
            ],
            usage=UsageInfo(
                prompt_tokens=0,
                completion_tokens=len(full_text),
                total_tokens=len(full_text),
            ),
        )

    # ── health ──────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


async def _stream_generator(
    provider: ChatProvider,
    messages: list[dict],
    model: str,
) -> AsyncIterator[str]:
    """Yields SSE `data:` payloads in OpenAI streaming format."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    # First chunk: role announcement
    first_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model,
        choices=[StreamChoice(delta=DeltaMessage(role="assistant", content=""))],
    )
    yield first_chunk.model_dump_json()

    # Content chunks
    async for text in provider.chat(messages, model):
        chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(content=text))],
        )
        yield chunk.model_dump_json()

    # Final chunk: finish_reason
    final_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=model,
        choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
    )
    yield final_chunk.model_dump_json()

    yield "[DONE]"
