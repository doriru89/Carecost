"""Chat routes. The seam between two wave-2 streams.

Stream C owns the app factory and mounts ``router`` at ``/api``. The Chat stream owns this file and
fills ``router`` with ``POST /chat`` (and whatever else chat needs). Neither stream edits the
other's file, so the two branches merge without touching the same lines.

The route does not declare ``response_model=ChatResponse``: the service validates the response
once with a ``ChatContext`` and returns its JSON (FastAPI would re-validate it without one).

Startup (R11): with ``CARECOST_ENV=production`` and no ``CARECOST_CHAT_LEDGER_PATH``, the app
refuses to start (``ChatConfigError`` from the router's lifespan).

Service wiring: ``request.app.state.chat_service`` when the app factory (or a test) set one;
otherwise one ``ChatService`` built from env vars on first use. If the factory sets
``app.state.catalog`` (stream C's ``Catalog``), the chat uses it; else a care-path-only catalog.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import Response

from app.chat.config import ChatSettings, check_production_paths
from app.chat.contracts import ChatRequest
from app.chat.netid import ClientAddressError, client_ip
from app.chat.service import ChatService, Content, RequestRejected

log = logging.getLogger(__name__)


@asynccontextmanager
async def _startup(app: FastAPI) -> AsyncIterator[None]:
    """R11: refuse to start in production without persistent ledger / review-log paths. The
    router's lifespan joins the app's when the factory includes it (FastAPI merges them)."""
    check_production_paths()
    yield


router = APIRouter(lifespan=_startup)

_lock = threading.Lock()


def get_service(request: Request) -> ChatService:
    state = request.app.state
    svc: ChatService | None = getattr(state, "chat_service", None)
    if svc is not None:
        return svc
    with _lock:
        svc = getattr(state, "chat_service", None)
        if svc is None:
            catalog = getattr(state, "catalog", None)
            svc = ChatService(ChatSettings.from_env(), Content.load(catalog))
            state.chat_service = svc
    assert svc is not None
    return svc


@router.post("/chat")
def chat(req: ChatRequest, request: Request) -> Response:
    svc = get_service(request)
    try:
        ip = client_ip(
            request.headers,
            request.client.host if request.client else None,
            svc.s.trusted_proxy_header,
            svc.s.trusted_proxy_hops,
        )
    except ClientAddressError as e:
        log.warning("chat: %s", e)
        raise HTTPException(status_code=400, detail="client address unavailable") from e
    try:
        body = svc.handle(req, ip)
    except RequestRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return Response(body, media_type="application/json")
