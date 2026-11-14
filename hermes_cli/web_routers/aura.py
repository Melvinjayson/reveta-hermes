"""Aura Settings: choose the chat model, store its API key and set USD caps."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field

from hermes_cli.web_deps import late

router = APIRouter()
_require_token = late("_require_token")


class ProviderUpdate(BaseModel):
    provider: str
    model: str = ""
    per_day_usd: Optional[float] = None
    per_chat_usd: Optional[float] = None
    api_key: str = Field(default="", max_length=512)


@router.get("/api/aura/voice")
async def aura_voice(request: Request):
    """Whether a continuous voice call can start here, and why not (no secrets)."""
    _require_token(request)
    from tools.aura_voice_call import settings

    return await asyncio.to_thread(settings)


@router.websocket("/api/audio/voice-call")
async def aura_voice_call(ws: WebSocket) -> None:
    """Aura's continuous Pipecat call: 16 kHz mic PCM in; transcripts, turn events and 24 kHz speech out.

    The client sends each transcript to the normal chat and ``{"type":"speak","text":...}`` with the
    reply, so tools and approvals stay on the chat turn and a barge-in only stops speech.
    """
    from hermes_cli.web_server_chat import _ws_auth_ok, _ws_request_is_allowed
    from hermes_cli.web_session_sockets import VOICE_CALL_SOCKET
    from tools.aura_voice_call import run_call

    if not _ws_auth_ok(ws, socket=VOICE_CALL_SOCKET):
        await ws.close(code=4401)
        return
    if not _ws_request_is_allowed(ws):
        await ws.close(code=4403)
        return
    await ws.accept(subprotocol=getattr(ws, "_hermes_ws_subprotocol", None))
    await run_call(ws)


@router.get("/api/aura/provider")
async def aura_provider(request: Request):
    _require_token(request)
    from tools.aura_provider import status

    return await asyncio.to_thread(status)


@router.put("/api/aura/provider")
async def set_aura_provider(body: ProviderUpdate, request: Request):
    _require_token(request)
    from tools.aura_provider import configure

    try:
        return await asyncio.to_thread(configure, body.provider, body.model, body.per_day_usd,
                                       body.per_chat_usd, body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
