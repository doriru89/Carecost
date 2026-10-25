"""Refresh failure handling for every source (P11, R11).

1. **Retry once.** :func:`with_retry` runs a fetch; on any error it waits and runs it again.
2. **Keep the last good copy.** A source that still fails keeps what it had: the hospital store's
   previous copy (the build already falls back to it), a TiC network's CURRENT run, a fee
   schedule's LATEST entry. Its old ``fetched_at`` stays, so freshness turns it stale on our side.
3. **Say so.** ``intermediate/refresh_status.json`` (under the data root) holds one entry per
   source and job: ``ok`` | ``stale_on_our_side`` (failed, last good copy kept, with the reason)
   | ``no_good_copy`` (failed and nothing to fall back to). The pack and the API read it so a
   failed source never reads as "no public price".
4. **Alert.** :func:`finish` sends one e-mail for the run's failures (:mod:`app.etl.alert`);
   with no sender configured it prints the alert text and the job exits non-zero.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from app.etl.alert import AlertSender, send_alert
from app.etl.config import Paths

T = TypeVar("T")
RETRIES = 1
RETRY_WAIT_S = float(os.environ.get("CARECOST_ETL_RETRY_WAIT_S") or 30)
STATUS_FILE = "refresh_status.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def with_retry(
    fn: Callable[[], T],
    what: str,
    *,
    retries: int = RETRIES,
    wait_s: float | None = None,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T | None, list[str]]:
    """-> (result or None, the error of every failed attempt)."""
    errors: list[str] = []
    wait_s = RETRY_WAIT_S if wait_s is None else wait_s
    for i in range(retries + 1):
        try:
            return fn(), errors
        except Exception as e:  # noqa: BLE001 - any failure is retried once, then reported
            errors.append(f"{type(e).__name__}: {e}")
            if i < retries:
                log(f"RETRY  {what}: {errors[-1]} (retrying once in {wait_s:.0f}s)")
                sleep(wait_s)
    return None, errors


@dataclass
class RefreshRun:
    """One job's refresh outcomes; :meth:`finish` writes the status file and alerts."""

    paths: Paths
    job: str
    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def ok(self, source_id: str, **info: Any) -> None:
        self.outcomes[source_id] = {"status": "ok", "job": self.job, "checked_at": _now(), **info}

    def failed(
        self, source_id: str, errors: list[str], last_good: dict[str, Any] | None
    ) -> dict[str, Any]:
        e = {
            "status": "stale_on_our_side" if last_good else "no_good_copy",
            "job": self.job,
            "checked_at": _now(),
            "attempts": len(errors),
            "reason": errors[-1] if errors else "unknown",
            "errors": errors,
            "last_good": last_good,
        }
        self.outcomes[source_id] = e
        return e

    @property
    def failures(self) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self.outcomes.items() if v["status"] != "ok"}

    def finish(
        self,
        *,
        sender: AlertSender | None = None,
        env: Mapping[str, str] | None = None,
        log: Callable[[str], None] = print,
    ) -> bool:
        """Write the status file; alert on failures. True = nothing failed."""
        write_status(self.paths, self.outcomes)
        fails = [
            {
                "source_id": sid,
                "status": e["status"],
                "reason": e["reason"],
                "last_good": _fmt_last_good(e.get("last_good")),
            }
            for sid, e in sorted(self.failures.items())
        ]
        if not fails:
            return True
        send_alert(fails, self.job, sender=sender, env=env, log=log)
        return False


def _fmt_last_good(lg: dict[str, Any] | None) -> str:
    if not lg:
        return ""
    return ", ".join(f"{k} {v}" for k, v in lg.items() if v)


def status_path(paths: Paths) -> Path:
    return paths.data / "intermediate" / STATUS_FILE


def read_status(paths: Paths) -> dict[str, dict[str, Any]]:
    p = status_path(paths)
    return json.loads(p.read_text())["sources"] if p.exists() else {}


def write_status(paths: Paths, outcomes: dict[str, dict[str, Any]]) -> Path:
    """Merge this run's outcomes into the status file (other sources keep their entries)."""
    p = status_path(paths)
    cur = read_status(paths)
    cur.update(outcomes)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp-{os.getpid()}")
    tmp.write_text(
        json.dumps({"version": 1, "updated_at": _now(), "sources": cur}, indent=1, sort_keys=True)
    )
    os.replace(tmp, p)
    return p
