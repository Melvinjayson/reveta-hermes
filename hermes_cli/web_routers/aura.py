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


class CapabilityUpdate(BaseModel):
    enabled: Optional[list[str]] = None
    mode: Optional[str] = Field(default=None, max_length=32)


@router.get("/api/aura/capabilities")
async def aura_capabilities(request: Request):
    _require_token(request)
    from tools.aura_capabilities import status

    return await asyncio.to_thread(status)


@router.put("/api/aura/capabilities")
async def set_aura_capabilities(body: CapabilityUpdate, request: Request):
    """Switch Hermes toolsets on or off for NEW conversations; running ones keep their tools."""
    _require_token(request)
    from tools.aura_capabilities import configure, set_mode

    try:
        if body.mode is not None:
            return await asyncio.to_thread(set_mode, body.mode)
        return await asyncio.to_thread(configure, body.enabled or [])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ProjectBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)


class ProjectMembership(BaseModel):
    session_id: str = Field(max_length=200)
    project_id: Optional[str] = Field(default=None, max_length=64)


async def _projects(call, *args):
    try:
        return await asyncio.to_thread(call, *args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/aura/projects")
async def aura_projects(request: Request):
    _require_token(request)
    from tools.aura_projects import list_all

    return await _projects(list_all)


@router.post("/api/aura/projects")
async def create_aura_project(body: ProjectBody, request: Request):
    _require_token(request)
    from tools.aura_projects import create

    return await _projects(create, body.name or "", body.description)


@router.patch("/api/aura/projects/{project_id}")
async def update_aura_project(project_id: str, body: ProjectBody, request: Request):
    _require_token(request)
    from tools.aura_projects import update

    return await _projects(update, project_id, body.name, body.description)


@router.delete("/api/aura/projects/{project_id}")
async def delete_aura_project(project_id: str, request: Request):
    """Deletes the project only; its conversations stay in history."""
    _require_token(request)
    from tools.aura_projects import remove

    return await _projects(remove, project_id)


@router.put("/api/aura/projects/membership")
async def set_aura_project_membership(body: ProjectMembership, request: Request):
    _require_token(request)
    from tools.aura_projects import assign

    return await _projects(assign, body.session_id, body.project_id)
