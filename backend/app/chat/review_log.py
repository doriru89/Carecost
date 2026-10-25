"""Local review log of model text (review round 2), so Austin can judge real outputs.

Off by default. ``CARECOST_CHAT_REVIEW_LOG=1`` turns it on; lines go to
``CARECOST_CHAT_REVIEW_LOG_PATH`` (JSON lines, appended). One line per model attempt:

    {"ts", "conversation_hash", "turn", "attempt", "message", "outcome", "rule", "reason",
     "final_kind"}

``outcome``: ``shown`` | ``accepted_not_shown`` (valid, but the service did not display it, e.g.
a lead_in for another question) | ``rejected`` | ``provider_error``. ``rule`` names the check that
rejected it: ``parse``, ``voice``, ``digits``, ``money``, ``condition_shapes``,
``diagnostic_cues``, ``site_names``, ``value``, ``urgency``, ``links`` (P13), ``contract`` or
``build``.

Never logged: the person's text, history, email, IP, chip answers or the prompt. The conversation
id is HMAC'd. ``reason`` for contract failures keeps only pydantic's location + message, never the
input value (an ``understood.evidence`` input is a quote of the person's words).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

log = logging.getLogger(__name__)

MAX_REASON = 300


def safe_reason(e: Exception) -> str:
    if isinstance(e, ValidationError):
        parts = [
            f"{'.'.join(str(x) for x in err.get('loc', ()))}: {err.get('msg', '')}"
            for err in e.errors(include_input=False, include_url=False)
        ]
        return "; ".join(parts)[:MAX_REASON]
    return str(e)[:MAX_REASON]


class ReviewLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, rows: list[dict[str, Any]], final_kind: str, now: datetime) -> None:
        if not rows:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lines = "".join(
                json.dumps({"ts": now.isoformat(), **r, "final_kind": final_kind},
                           ensure_ascii=False) + "\n"
                for r in rows
            )  # fmt: skip
            with self._lock, self.path.open("a", encoding="utf-8") as fh:
                fh.write(lines)
        except OSError as e:  # the review log never breaks a chat turn
            log.warning("chat review log: %s", e)
