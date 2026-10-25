"""A5 item 5 (R11, P11): retry once, keep the last good copy marked stale_on_our_side, alert.

Every sender here is fake: nothing is sent and no address is used beyond example.invalid."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.etl import alert, refresh
from app.etl import fetch as fetch_mod
from app.etl.cli import main
from app.etl.config import Paths

ENV = {"CARECOST_ALERT_EMAIL": "ops@example.invalid", "CARECOST_SMTP_HOST": "smtp.example.invalid"}


class FakeSender:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise OSError("connection refused")
        self.sent.append((to, subject, body))


def test_retry_once_then_give_up():
    calls = []

    def flaky():
        calls.append(1)
        raise fetch_mod.FetchError("HTTP 503")

    got, errs = refresh.with_retry(flaky, "x", wait_s=0, log=lambda _m: None)
    assert got is None and len(calls) == 2 and errs == ["FetchError: HTTP 503"] * 2


def test_retry_succeeds_on_the_second_try():
    n = iter([RuntimeError("boom"), "ok"])

    def f():
        v = next(n)
        if isinstance(v, Exception):
            raise v
        return v

    assert refresh.with_retry(f, "x", wait_s=0, log=lambda _m: None) == (
        "ok",
        ["RuntimeError: boom"],
    )


def test_failure_writes_stale_status_and_alerts(tmp_path):
    run = refresh.RefreshRun(Paths(tmp_path), "test job")
    run.ok("a_mrf", sha256="aa")
    run.failed("b_mrf", ["FetchError: HTTP 503"] * 2, {"sha256": "bb", "fetched_at": "2026-10-01"})
    run.failed("c_mrf", ["FetchError: TLS"], None)
    s = FakeSender()
    assert run.finish(sender=s, env=ENV, log=lambda _m: None) is False
    st = refresh.read_status(Paths(tmp_path))
    assert st["a_mrf"]["status"] == "ok"
    assert st["b_mrf"]["status"] == "stale_on_our_side" and st["b_mrf"]["attempts"] == 2
    assert st["b_mrf"]["last_good"]["sha256"] == "bb"
    assert st["c_mrf"]["status"] == "no_good_copy"
    ((to, subject, body),) = s.sent
    assert to == "ops@example.invalid" and "2 sources failed" in subject
    assert "b_mrf: stale_on_our_side" in body and "HTTP 503" in body
    assert "no public price" in body  # says the failure never reads as no price


def test_no_sender_configured_fails_loudly_with_the_alert_text(tmp_path):
    logs: list[str] = []
    run = refresh.RefreshRun(Paths(tmp_path), "job")
    run.failed("b_mrf", ["FetchError: HTTP 503"], {"sha256": "bb"})
    assert run.finish(env={}, log=logs.append) is False
    text = "\n".join(logs)
    assert "NOT SENT" in text and "CARECOST_ALERT_EMAIL" in text and "b_mrf" in text


def test_broken_mail_server_still_logs_the_alert():
    logs: list[str] = []
    ok = alert.send_alert([{"source_id": "x", "status": "stale_on_our_side", "reason": "r",
                            "last_good": ""}], "job", sender=FakeSender(fail=True), env=ENV,
                          log=logs.append)  # fmt: skip
    assert ok is False and any("connection refused" in m for m in logs)


def test_smtp_sender_from_env_uses_only_env_and_a_fake_transport():
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host, self.port = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            sent.append("starttls")

        def login(self, u, p):
            sent.append(("login", u))

        def send_message(self, msg):
            sent.append(msg)

    s = alert.sender_from_env({**ENV, "CARECOST_SMTP_USER": "u", "CARECOST_SMTP_PASSWORD": "p"})
    assert isinstance(s, alert.SmtpSender) and s.port == 587
    s.smtp_factory = FakeSMTP
    s.send("ops@example.invalid", "subj", "body")
    assert sent[0] == "starttls" and sent[1] == ("login", "u")
    assert sent[2]["To"] == "ops@example.invalid" and sent[2]["Subject"] == "subj"
    assert alert.sender_from_env({}) is None
    with pytest.raises(ValueError):
        alert.sender_from_env({"CARECOST_SMTP_HOST": "h", "CARECOST_SMTP_TLS": "maybe"})


def test_no_recipient_or_credential_is_committed():
    """Workflows pass alert settings only from secrets; config files carry no address."""
    import re

    root = Path(__file__).resolve().parents[3]
    for f in (root / ".github" / "workflows").glob("*.yml"):
        for ln in f.read_text().splitlines():
            m = re.match(r"\s*(CARECOST_(ALERT_EMAIL|SMTP_\w+)):\s*(.*)$", ln)
            if m:
                assert m.group(3).startswith("${{ secrets."), f"{f.name}: {ln.strip()}"
    for f in (root / "data" / "etl").rglob("*.yaml"):
        assert not re.search(r"[\w.+-]+@[\w-]+\.(com|org|net)", f.read_text()), f.name


def test_hospital_fetch_failure_keeps_last_good_copy_and_exits_1(tmp_path, monkeypatch, capsys):
    """End to end through the CLI: the download fails twice -> status stale_on_our_side with the
    stored copy, alert text in the log (no sender configured), exit 1."""
    data = tmp_path / "data"
    store = data / "raw" / "store" / "mgh_mrf"
    store.mkdir(parents=True)
    (store / "abc.csv").write_text("x")
    rec = {"source_id": "mgh_mrf", "method": "download", "url": "https://x.invalid/f.csv",
           "final_url": None, "sha256": "abc", "bytes": 1, "relpath": "mgh_mrf/abc.csv",
           "fetched_at": "2026-10-01T00:00:00+00:00", "status": "new",
           "http_last_modified": None, "etag": None}  # fmt: skip
    (data / "raw" / "store" / "fetch_manifest.jsonl").write_text(json.dumps(rec) + "\n")
    calls = []

    def boom(spec, settings, paths, client=None):
        calls.append(spec.source_id)
        raise fetch_mod.FetchError(f"{spec.source_id}: HTTP 503")

    monkeypatch.setattr(fetch_mod, "fetch_source", boom)
    monkeypatch.setattr(refresh, "RETRY_WAIT_S", 0.0)
    for k in ("CARECOST_ALERT_EMAIL", "CARECOST_SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    assert main(["--data-dir", str(data), "fetch", "--source", "mgh_mrf"]) == 1
    assert calls == ["mgh_mrf", "mgh_mrf"]
    st = refresh.read_status(Paths(data))["mgh_mrf"]
    assert st["status"] == "stale_on_our_side" and st["last_good"]["sha256"] == "abc"
    assert st["last_good"]["fetched_at"].startswith("2026-10-01")
    out = capsys.readouterr().out
    assert "RETRY  mgh_mrf" in out and "ALERT  NOT SENT" in out
