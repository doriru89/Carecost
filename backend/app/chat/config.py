"""Chat settings, read from env vars only (never from a file, never logged).

| Env var | Default | Meaning |
|---|---|---|
| ``CARECOST_CHAT_PROVIDER`` | ``gemini`` | ``gemini`` (D26), ``lava`` (D15 switch, OpenAI-compatible) or ``off`` |
| ``CARECOST_GEMINI_API_KEY`` | — | Gemini key (paid tier, D26). Without it the AI pauses (provider_unavailable) |
| ``CARECOST_GEMINI_MODEL`` | ``gemini-3.8-flash`` | model id |
| ``CARECOST_GEMINI_THINKING_LEVEL`` | ``low`` | ``thinkingConfig.thinkingLevel``; empty string omits the field |
| ``CARECOST_LAVA_API_KEY`` | — | Lava key, only when the provider is ``lava`` |
| ``CARECOST_LAVA_BASE_URL`` | ``https://api.lava.so/v1`` | Lava gateway |
| ``CARECOST_LAVA_MODEL`` | ``gemini-3.8-flash`` | model name Lava routes to |
| ``CARECOST_CHAT_HMAC_SECRET`` | — | HMAC key for IP and email hashes. Without it the AI pauses |
| ``CARECOST_ENV`` | — | ``production`` makes the two paths below required: the app refuses to start without them (R11) |
| ``CARECOST_CHAT_LEDGER_PATH`` | dev: ``<tmp>/carecost_chat_ledger.sqlite``; production: required | SQLite ledger; on Railway a volume path, e.g. ``/data/chat_ledger.sqlite`` |
| ``CARECOST_TRUSTED_PROXY_HEADER`` | — (use the socket peer) | e.g. ``X-Forwarded-For`` behind Railway's proxy |
| ``CARECOST_TRUSTED_PROXY_HOPS`` | ``1`` | for X-Forwarded-For: how many proxies we trust (take the Nth address from the right) |
| ``CARECOST_CHAT_IP_SOFT_USD`` / ``_IP_HARD_USD`` | ``1.0`` / ``2.0`` | per hashed IP per provider day (D2) |
| ``CARECOST_CHAT_GLOBAL_DAILY_USD`` | ``5.0`` | all IPs together per provider day |
| ``CARECOST_CHAT_IP_TURN_CAP`` | ``40`` | LLM turns per hashed IP per provider day |
| ``CARECOST_CHAT_PRICE_IN_PER_MTOK`` / ``_OUT_PER_MTOK`` | the model's list price | override the price table |
| ``CARECOST_CHAT_REVIEW_LOG`` | off | ``1`` / ``true`` writes one JSON line per model attempt (local review only) |
| ``CARECOST_CHAT_REVIEW_LOG_PATH`` | dev: ``<tmp>/carecost_chat_review.jsonl``; production with the log on: required | where those lines go |

R11 (wave-2 review): a ledger under the temp dir is wiped on every container restart, which
silently resets every budget cap. Dev keeps the temp default; production refuses to start.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


def _f(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v else default


def _i(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v else default


def _s(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


class ChatConfigError(RuntimeError):
    """A setting that production must not run without (raised at startup, never at a turn)."""


def is_production() -> bool:
    return (os.environ.get("CARECOST_ENV") or "").strip().lower() == "production"


def check_production_paths() -> None:
    """R11: in production the ledger (and the review log, when on) needs an explicit path."""
    if not is_production():
        return
    if not _s("CARECOST_CHAT_LEDGER_PATH"):
        raise ChatConfigError(
            "CARECOST_ENV=production needs CARECOST_CHAT_LEDGER_PATH (a persistent volume path); "
            "the temp-dir default would reset every budget cap on restart"
        )
    review = (_s("CARECOST_CHAT_REVIEW_LOG", "") or "").lower() in ("1", "true", "yes")
    if review and not _s("CARECOST_CHAT_REVIEW_LOG_PATH"):
        raise ChatConfigError(
            "CARECOST_ENV=production with CARECOST_CHAT_REVIEW_LOG on needs "
            "CARECOST_CHAT_REVIEW_LOG_PATH"
        )


@dataclass(frozen=True)
class ChatSettings:
    provider: str = "gemini"
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_model: str = "gemini-3.8-flash"
    gemini_thinking_level: str | None = "low"
    lava_api_key: str | None = field(default=None, repr=False)
    lava_base_url: str = "https://api.lava.so/v1"
    lava_model: str = "gemini-3.8-flash"
    hmac_secret: bytes | None = field(default=None, repr=False)
    ledger_path: Path = Path(tempfile.gettempdir()) / "carecost_chat_ledger.sqlite"
    trusted_proxy_header: str | None = None
    trusted_proxy_hops: int = 1
    ip_soft_usd: float = 1.0
    ip_hard_usd: float = 2.0
    global_daily_usd: float = 5.0
    ip_turn_cap: int = 40
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None
    max_output_tokens: int = 1024
    review_log: bool = False
    review_log_path: Path = Path(tempfile.gettempdir()) / "carecost_chat_review.jsonl"
    timeout_s: float = 20.0

    @classmethod
    def from_env(cls) -> ChatSettings:
        check_production_paths()
        secret = _s("CARECOST_CHAT_HMAC_SECRET")
        thinking = os.environ.get("CARECOST_GEMINI_THINKING_LEVEL")
        return cls(
            provider=(_s("CARECOST_CHAT_PROVIDER", "gemini") or "gemini").lower(),
            gemini_api_key=_s("CARECOST_GEMINI_API_KEY"),
            gemini_model=_s("CARECOST_GEMINI_MODEL", cls.gemini_model) or cls.gemini_model,
            gemini_thinking_level=cls.gemini_thinking_level
            if thinking is None
            else (thinking or None),
            lava_api_key=_s("CARECOST_LAVA_API_KEY"),
            lava_base_url=_s("CARECOST_LAVA_BASE_URL", cls.lava_base_url) or cls.lava_base_url,
            lava_model=_s("CARECOST_LAVA_MODEL", cls.lava_model) or cls.lava_model,
            hmac_secret=secret.encode() if secret else None,
            ledger_path=Path(
                _s("CARECOST_CHAT_LEDGER_PATH", str(cls.ledger_path)) or cls.ledger_path
            ),
            trusted_proxy_header=_s("CARECOST_TRUSTED_PROXY_HEADER"),
            trusted_proxy_hops=_i("CARECOST_TRUSTED_PROXY_HOPS", 1),
            ip_soft_usd=_f("CARECOST_CHAT_IP_SOFT_USD", 1.0),
            ip_hard_usd=_f("CARECOST_CHAT_IP_HARD_USD", 2.0),
            global_daily_usd=_f("CARECOST_CHAT_GLOBAL_DAILY_USD", 5.0),
            ip_turn_cap=_i("CARECOST_CHAT_IP_TURN_CAP", 40),
            price_in_per_mtok=_f("CARECOST_CHAT_PRICE_IN_PER_MTOK", -1)
            if _s("CARECOST_CHAT_PRICE_IN_PER_MTOK")
            else None,
            price_out_per_mtok=_f("CARECOST_CHAT_PRICE_OUT_PER_MTOK", -1)
            if _s("CARECOST_CHAT_PRICE_OUT_PER_MTOK")
            else None,
            review_log=(_s("CARECOST_CHAT_REVIEW_LOG", "") or "").lower() in ("1", "true", "yes"),
            review_log_path=Path(
                _s("CARECOST_CHAT_REVIEW_LOG_PATH", str(cls.review_log_path)) or cls.review_log_path
            ),
        )
