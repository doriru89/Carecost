"""
Lightweight crisis-language detection for intake / assistant flows.

Not a clinical instrument—pattern-based triage to stop estimate framing and surface crisis resources.
"""

from __future__ import annotations

import re
from typing import Any

# Multi-word / phrase checks (lowercase). Tuned to reduce false positives vs single generic words.
_CRISIS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bkill\s+myself\b"),
    re.compile(r"\bkilling\s+myself\b"),
    re.compile(r"\bend\s+my\s+life\b"),
    re.compile(r"\bwant\s+to\s+die\b"),
    re.compile(r"\bdon'?t\s+want\s+to\s+live\b"),
    re.compile(r"\bbetter\s+off\s+dead\b"),
    re.compile(r"\bsuicid\w*\b"),
    re.compile(r"\bself[- ]harm\w*\b"),
    re.compile(r"\bhurt\s+myself\b"),
    re.compile(r"\bcutting\s+myself\b"),
    re.compile(r"\boverdose\b"),
    re.compile(r"\bend\s+it\s+all\b"),
    re.compile(r"\bno\s+reason\s+to\s+live\b"),
    re.compile(r"\btake\s+all\s+(my\s+)?pills\b"),
)

_CRISIS_SUBSTRINGS: tuple[str, ...] = (
    "want to kill myself",
    "going to kill myself",
    "going to end it",
)

DEFAULT_CRISIS_MESSAGE = (
    "If you are in immediate danger, call 911. "
    "If you are thinking about hurting yourself or ending your life, call or text **988** (Suicide & Crisis Lifeline) "
    "or visit 988lifeline.org. "
    "This app only helps with cost estimates and is not for emergencies or crisis care—we have stopped that kind of chat here."
)

# Plain text for SMS/chat (no markdown)
DEFAULT_CRISIS_MESSAGE_PLAIN = DEFAULT_CRISIS_MESSAGE.replace("**", "")

SAFETY_RESOURCES: list[dict[str, str]] = [
    {"label": "988 — call or text", "href": "tel:988"},
    {"label": "911 — emergency", "href": "tel:911"},
    {"label": "988 Lifeline (web)", "href": "https://988lifeline.org/"},
]


def crisis_scan_text(text: str) -> bool:
    """Return True if text should trigger safety hold (crisis resources, no estimates)."""
    if not text or not text.strip():
        return False
    low = text.lower()
    for sub in _CRISIS_SUBSTRINGS:
        if sub in low:
            return True
    for pat in _CRISIS_PATTERNS:
        if pat.search(low):
            return True
    return False


def crisis_scan_messages(symptom_notes: str, messages: list[dict[str, Any]]) -> bool:
    """Scan free-text notes plus all user turns in the conversation."""
    parts: list[str] = [symptom_notes.strip()]
    for m in messages:
        if str(m.get("role", "")).lower() == "user":
            parts.append(str(m.get("content", "")).strip())
    blob = " ".join(p for p in parts if p)
    return crisis_scan_text(blob)


def crisis_response_payload() -> dict[str, Any]:
    """Structured extras for API responses when safety_hold is True."""
    return {
        "safety_message": DEFAULT_CRISIS_MESSAGE_PLAIN,
        "safety_resources": SAFETY_RESOURCES,
    }
