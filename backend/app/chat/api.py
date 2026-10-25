"""Chat routes. The seam between two wave-2 streams.

Stream C owns the app factory and mounts ``router`` at ``/api``. The Chat stream owns this file and
fills ``router`` with ``POST /chat`` (and whatever else chat needs). Neither stream edits the
other's file, so the two branches merge without touching the same lines.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
