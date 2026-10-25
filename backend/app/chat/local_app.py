"""A tiny app that mounts only the chat router, for the Chat stream's own local testing (port 8101).
The real app factory is stream C's; it mounts ``app.chat.api.router`` at ``/api`` the same way.

    cd backend
    CARECOST_CHAT_HMAC_SECRET=dev-only-secret CARECOST_CHAT_LEDGER_PATH=/tmp/cc_chat.sqlite \\
      uv run --frozen uvicorn app.chat.local_app:app --host 127.0.0.1 --port 8101
"""

from __future__ import annotations

from fastapi import FastAPI

from app.chat.api import router


def create_app() -> FastAPI:
    app = FastAPI(title="CareCost chat (local)")
    app.include_router(router, prefix="/api")
    return app


app = create_app()
