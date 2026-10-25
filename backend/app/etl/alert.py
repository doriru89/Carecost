"""Refresh-failure alert e-mail (P11): pluggable sender, configured only by environment variables.

    CARECOST_ALERT_EMAIL     recipient (required to send; never committed)
    CARECOST_SMTP_HOST       SMTP server (required to send)
    CARECOST_SMTP_PORT       default 587
    CARECOST_SMTP_USER       optional login
    CARECOST_SMTP_PASSWORD   optional login (env / CI secret only)
    CARECOST_SMTP_FROM       default: CARECOST_SMTP_USER, else the recipient
    CARECOST_SMTP_TLS        starttls (default) | ssl | none

With no sender configured the alert text goes to the log and :func:`send_alert` returns False,
so the job exits non-zero: a failed refresh is never silent. Tests pass a fake sender; nothing
here is called with a real address in this repo.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

ENV_TO = "CARECOST_ALERT_EMAIL"


class AlertSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


@dataclass
class SmtpSender:
    host: str
    port: int = 587
    user: str | None = None
    password: str | None = None
    sender: str | None = None
    tls: str = "starttls"
    timeout_s: float = 30.0
    smtp_factory: Callable[..., smtplib.SMTP] | None = None  # tests inject a fake transport

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender or self.user or to
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        ctx = ssl.create_default_context()
        if self.smtp_factory is not None:
            conn = self.smtp_factory(self.host, self.port, timeout=self.timeout_s)
        elif self.tls == "ssl":
            conn = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout_s, context=ctx)
        else:
            conn = smtplib.SMTP(self.host, self.port, timeout=self.timeout_s)
        with conn as s:
            if self.tls == "starttls":
                s.starttls(context=ctx)
            if self.user and self.password:
                s.login(self.user, self.password)
            s.send_message(msg)


def sender_from_env(env: Mapping[str, str] | None = None) -> AlertSender | None:
    e = os.environ if env is None else env
    host = (e.get("CARECOST_SMTP_HOST") or "").strip()
    if not host:
        return None
    tls = (e.get("CARECOST_SMTP_TLS") or "starttls").strip().lower()
    if tls not in ("starttls", "ssl", "none"):
        raise ValueError(f"CARECOST_SMTP_TLS={tls!r}: use starttls, ssl or none")
    return SmtpSender(
        host=host,
        port=int(e.get("CARECOST_SMTP_PORT") or (465 if tls == "ssl" else 587)),
        user=e.get("CARECOST_SMTP_USER") or None,
        password=e.get("CARECOST_SMTP_PASSWORD") or None,
        sender=e.get("CARECOST_SMTP_FROM") or None,
        tls=tls,
    )


def compose(failures: list[dict[str, str]], job: str) -> tuple[str, str]:
    n = len(failures)
    subject = f"[CareCost] {job}: {n} source{'s' if n != 1 else ''} failed to refresh"
    lines = [
        f"{job}: {n} source(s) could not be refreshed after one retry.",
        "Each keeps its last good copy, marked stale_on_our_side; none reads as 'no public price'.",
        "",
    ]
    for f in failures:
        lines.append(f"- {f['source_id']}: {f['status']}")
        lines.append(f"    reason: {f['reason']}")
        if f.get("last_good"):
            lines.append(f"    last good copy: {f['last_good']}")
    lines += ["", "Status file: intermediate/refresh_status.json under the ETL data root."]
    return subject, "\n".join(lines) + "\n"


def send_alert(
    failures: list[dict[str, str]],
    job: str,
    *,
    sender: AlertSender | None = None,
    env: Mapping[str, str] | None = None,
    log: Callable[[str], None] = print,
) -> bool:
    """True only when the alert was handed to a configured sender."""
    if not failures:
        return True
    subject, body = compose(failures, job)
    e = os.environ if env is None else env
    to = (e.get(ENV_TO) or "").strip()
    try:
        sender = sender or sender_from_env(e)
    except ValueError as ex:
        log(f"ALERT  sender misconfigured: {ex}")
        sender = None
    if sender is None or not to:
        missing = [k for k, v in ((ENV_TO, to), ("CARECOST_SMTP_HOST", sender)) if not v]
        log(f"ALERT  NOT SENT (no sender configured: set {', '.join(missing)}). Alert text:")
        for ln in (subject, *body.splitlines()):
            log(f"ALERT  {ln}")
        return False
    try:
        sender.send(to, subject, body)
    except Exception as ex:  # noqa: BLE001 - a broken mail server must not hide the alert
        log(f"ALERT  NOT SENT ({type(ex).__name__}: {ex}). Alert text:")
        for ln in (subject, *body.splitlines()):
            log(f"ALERT  {ln}")
        return False
    log(f"ALERT  sent to the CARECOST_ALERT_EMAIL recipient: {subject}")
    return True
