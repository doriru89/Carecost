"""SQLite budget ledger (D2, P8). Lives on a Railway volume (``CARECOST_CHAT_LEDGER_PATH``).

Reserve before every LLM call, settle after it. A reservation counts as spent until it is settled
with the real cost, so a crash between the two over-counts, never under-counts. The check and
the insert happen in one ``BEGIN IMMEDIATE`` transaction (SQLite's write lock), so concurrent
requests cannot both see room for one more call: no double spend under threads or processes.

Day = the provider's quota day (Gemini resets at midnight Pacific), so caps reset when the
provider's own limits do.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo

PROVIDER_TZ = ZoneInfo("America/Los_Angeles")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    email_hash TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    turn_key TEXT NOT NULL,
    reserved_usd REAL NOT NULL,
    actual_usd REAL,
    created_at REAL NOT NULL,
    settled_at REAL
);
CREATE INDEX IF NOT EXISTS reservations_day_ip ON reservations(day, ip_hash);
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    ip_hash TEXT NOT NULL,
    email_hash TEXT NOT NULL,
    turns INTEGER NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


def provider_day(now: datetime) -> str:
    return now.astimezone(PROVIDER_TZ).date().isoformat()


def resets_at(now: datetime) -> datetime:
    local = now.astimezone(PROVIDER_TZ)
    nxt = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), PROVIDER_TZ)
    return nxt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Caps:
    ip_soft_usd: float
    ip_hard_usd: float
    global_usd: float
    ip_turn_cap: int


@dataclass(frozen=True)
class Usage:
    ip_spent_usd: float
    ip_turns: int
    global_spent_usd: float


@dataclass(frozen=True)
class Reservation:
    id: int
    amount_usd: float


class Refused(Exception):
    def __init__(self, reason: str, usage: Usage):
        super().__init__(reason)
        self.reason = reason  # "ip_daily_cap" | "wallet_exhausted"
        self.usage = usage


class Ledger:
    def __init__(
        self,
        path: Path | str,
        caps: Caps,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.path = Path(path)
        self.caps = caps
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    # one connection per thread; autocommit mode, transactions opened explicitly
    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.conn = c
        return c

    def _usage(self, c: sqlite3.Connection, day: str, ip_hash: str) -> Usage:
        spent_expr = "COALESCE(SUM(COALESCE(actual_usd, reserved_usd)), 0)"
        ip_spent, ip_turns = c.execute(
            f"SELECT {spent_expr}, COUNT(DISTINCT turn_key) FROM reservations "
            "WHERE day = ? AND ip_hash = ?",
            (day, ip_hash),
        ).fetchone()
        (glob,) = c.execute(
            f"SELECT {spent_expr} FROM reservations WHERE day = ?", (day,)
        ).fetchone()
        return Usage(float(ip_spent), int(ip_turns), float(glob))

    def usage(self, ip_hash: str) -> Usage:
        return self._usage(self._conn(), provider_day(self.clock()), ip_hash)

    def _turn_used(self, c: sqlite3.Connection, day: str, turn_key: str) -> bool:
        return (
            c.execute(
                "SELECT 1 FROM reservations WHERE day = ? AND turn_key = ? LIMIT 1", (day, turn_key)
            ).fetchone()
            is not None
        )

    def reserve(
        self,
        *,
        ip_hash: str,
        email_hash: str,
        conversation_id: str,
        turn_key: str,
        amount_usd: float,
    ) -> Reservation:
        """Atomically check every cap and hold ``amount_usd``. Raises ``Refused``.

        A second reservation for the same ``turn_key`` (the one retry) does not count as a new
        turn, but its dollars count like any other."""
        c = self._conn()
        day = provider_day(self.clock())
        c.execute("BEGIN IMMEDIATE")
        try:
            u = self._usage(c, day, ip_hash)
            new_turn = not self._turn_used(c, day, turn_key)
            if new_turn and u.ip_turns >= self.caps.ip_turn_cap:
                raise Refused("ip_daily_cap", u)
            if u.ip_spent_usd + amount_usd > self.caps.ip_hard_usd + 1e-12:
                raise Refused("ip_daily_cap", u)
            if u.global_spent_usd + amount_usd > self.caps.global_usd + 1e-12:
                raise Refused("wallet_exhausted", u)
            cur = c.execute(
                "INSERT INTO reservations (day, ip_hash, email_hash, conversation_id, turn_key, "
                "reserved_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (day, ip_hash, email_hash, conversation_id, turn_key, amount_usd, time.time()),
            )
            c.execute("COMMIT")
            return Reservation(int(cur.lastrowid or 0), amount_usd)
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def settle(self, reservation: Reservation, actual_usd: float) -> None:
        """Replace the hold with the real cost (may be higher than the hold: it is still counted)."""
        c = self._conn()
        c.execute(
            "UPDATE reservations SET actual_usd = ?, settled_at = ? WHERE id = ? AND actual_usd IS NULL",
            (max(0.0, actual_usd), time.time(), reservation.id),
        )

    # ------------------------------------------------------------------ conversations

    def next_turn(
        self,
        conversation_id: str | None,
        ip_hash: str,
        email_hash: str,
        new_id: Callable[[], str],
    ) -> tuple[str, int]:
        """(conversation_id, this turn's number). An unknown id, or one issued to another IP,
        starts a new conversation with a fresh id (a client cannot pick its own id or borrow
        someone else's count)."""
        c = self._conn()
        now = time.time()
        c.execute("BEGIN IMMEDIATE")
        try:
            row = None
            if conversation_id is not None:
                row = c.execute(
                    "SELECT ip_hash, turns FROM conversations WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
            if row is None or row[0] != ip_hash:
                cid = new_id()
                c.execute(
                    "INSERT INTO conversations VALUES (?, ?, ?, 1, ?, ?)",
                    (cid, ip_hash, email_hash, now, now),
                )
                c.execute("COMMIT")
                return cid, 1
            turns = int(row[1]) + 1
            c.execute(
                "UPDATE conversations SET turns = ?, updated_at = ?, email_hash = ? "
                "WHERE conversation_id = ?",
                (turns, now, email_hash, conversation_id),
            )
            c.execute("COMMIT")
            assert conversation_id is not None
            return conversation_id, turns
        except BaseException:
            c.execute("ROLLBACK")
            raise
