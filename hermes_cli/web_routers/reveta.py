"""Reveta ecosystem adapter: metadata only, no writes or credential disclosure."""
from __future__ import annotations

import asyncio
from fastapi import APIRouter, Request
from hermes_cli.web_deps import late
from reveta_ecosystem.foundation import overview

router = APIRouter()
_require_token = late("_require_token")


@router.get("/api/reveta/overview")
async def reveta_overview(request: Request):
    # Explicit guard in addition to dashboard's gated middleware.
    _require_token(request)
    return await asyncio.to_thread(overview)
