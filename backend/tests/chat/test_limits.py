"""Abuse limits (D2, P8): ledger caps, reserve-then-settle, concurrency, provider day, turn caps,
identity hashing, trusted proxy header, IPv6 /64, provider failure and the llm_invalid path."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.chat.contracts import MAX_TURNS_PER_CONVERSATION
from app.chat.ledger import Caps, Ledger, Refused, provider_day, resets_at
from app.chat.llm import ProviderError
from app.chat.netid import ClientAddressError, client_ip, hash_email, hash_ip, ip_key

from .util import NOW, llm, req, run, service

CAPS = Caps(ip_soft_usd=1.0, ip_hard_usd=2.0, global_usd=5.0, ip_turn_cap=40)


def _ledger(tmp_path, caps=CAPS, clock=lambda: NOW) -> Ledger:
    return Ledger(tmp_path / "l.sqlite", caps, clock)


def _res(led: Ledger, ip="ipA", amount=0.5, turn=None, conv="c1"):
    return led.reserve(
        ip_hash=ip, email_hash="e", conversation_id=conv,
        turn_key=turn or f"t{threading.get_ident()}-{id(object())}", amount_usd=amount,
    )  # fmt: skip


# --------------------------------------------------------------------------- ledger


def test_hard_cap_per_ip(tmp_path):
    led = _ledger(tmp_path)
    for _ in range(4):
        _res(led, amount=0.5)
    with pytest.raises(Refused) as e:
        _res(led, amount=0.01)
    assert e.value.reason == "ip_daily_cap"
    _res(led, ip="ipB", amount=0.5)  # another IP is not affected


def test_global_daily_cap(tmp_path):
    led = _ledger(tmp_path, Caps(1.0, 2.0, 1.0, 40))
    _res(led, ip="a", amount=0.6)
    with pytest.raises(Refused) as e:
        _res(led, ip="b", amount=0.6)
    assert e.value.reason == "wallet_exhausted"


def test_turn_cap_counts_turns_not_attempts(tmp_path):
    led = _ledger(tmp_path, Caps(1.0, 2.0, 5.0, 2))
    _res(led, amount=0.01, turn="t1")
    _res(led, amount=0.01, turn="t1")  # the retry of the same turn
    _res(led, amount=0.01, turn="t2")
    assert led.usage("ipA").ip_turns == 2
    with pytest.raises(Refused):
        _res(led, amount=0.01, turn="t3")
    _res(led, amount=0.01, turn="t2")  # a retry inside an admitted turn is still allowed


def test_reserve_then_settle(tmp_path):
    led = _ledger(tmp_path)
    r = _res(led, amount=0.5)
    assert led.usage("ipA").ip_spent_usd == pytest.approx(0.5)  # an open hold counts as spent
    led.settle(r, 0.01)
    assert led.usage("ipA").ip_spent_usd == pytest.approx(0.01)
    led.settle(r, 0.4)  # settling twice does nothing
    assert led.usage("ipA").ip_spent_usd == pytest.approx(0.01)


def test_unsettled_hold_stays_counted_across_restart(tmp_path):
    led = _ledger(tmp_path)
    _res(led, amount=0.7)
    led2 = _ledger(tmp_path)  # a new process on the same volume
    assert led2.usage("ipA").ip_spent_usd == pytest.approx(0.7)


@pytest.mark.parametrize("n_threads", [16, 64])
def test_concurrent_reserves_never_double_spend(tmp_path, n_threads):
    led = _ledger(tmp_path, Caps(1.0, 2.0, 100.0, 1000))
    ok: list[int] = []
    refused: list[int] = []
    barrier = threading.Barrier(n_threads)

    def worker(i: int) -> None:
        barrier.wait()
        try:
            _res(led, amount=0.3, turn=f"t{i}")
            ok.append(i)
        except Refused:
            refused.append(i)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # 2.0 / 0.3 -> exactly 6 holds fit
    assert len(ok) == 6 and len(refused) == n_threads - 6
    total = (
        sqlite3.connect(tmp_path / "l.sqlite")
        .execute("SELECT SUM(reserved_usd) FROM reservations")
        .fetchone()[0]
    )
    assert total == pytest.approx(1.8) and total <= 2.0


def test_concurrent_turn_cap(tmp_path):
    led = _ledger(tmp_path, Caps(100.0, 100.0, 100.0, 5))
    ok = []
    barrier = threading.Barrier(30)

    def worker(i):
        barrier.wait()
        try:
            _res(led, amount=0.001, turn=f"t{i}")
            ok.append(i)
        except Refused:
            pass

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(ok) == 5


def test_provider_day_is_pacific(tmp_path):
    # 2026-10-25 06:59 UTC is still 2026-10-24 in Los Angeles (PDT, UTC-7)
    assert provider_day(datetime(2026, 10, 25, 6, 59, tzinfo=timezone.utc)) == "2026-10-24"
    assert provider_day(datetime(2026, 10, 25, 7, 0, tzinfo=timezone.utc)) == "2026-10-25"
    assert resets_at(NOW) == datetime(2026, 10, 25, 7, 0, tzinfo=timezone.utc)
    t = {"now": NOW}
    led = _ledger(tmp_path, clock=lambda: t["now"])
    for _ in range(4):
        _res(led, amount=0.5)
    with pytest.raises(Refused):
        _res(led, amount=0.5)
    t["now"] = NOW + timedelta(hours=14)  # past midnight Pacific
    _res(led, amount=0.5)


def test_conversation_ids_are_server_issued_and_bound_to_the_ip(tmp_path):
    led = _ledger(tmp_path)
    ids = iter(["c_aaaaaaaaaaaaaaaaaaaa", "c_bbbbbbbbbbbbbbbbbbbb", "c_cccccccccccccccccccc"])
    cid, n = led.next_turn(None, "ipA", "e", lambda: next(ids))
    assert (cid, n) == ("c_aaaaaaaaaaaaaaaaaaaa", 1)
    assert led.next_turn(cid, "ipA", "e", lambda: next(ids)) == (cid, 2)
    # another IP presenting the same id gets a fresh conversation, not this one's count
    assert led.next_turn(cid, "ipB", "e", lambda: next(ids)) == ("c_bbbbbbbbbbbbbbbbbbbb", 1)
    # a made-up id is not adopted
    assert led.next_turn("c_madeupmadeupmadeup", "ipA", "e", lambda: next(ids))[0] == (
        "c_cccccccccccccccccccc"
    )


# --------------------------------------------------------------------------- identity


def test_trusted_header_only():
    h = {"X-Forwarded-For": "1.1.1.1, 198.51.100.9", "X-Real-IP": "6.6.6.6"}
    assert client_ip(h, "10.0.0.1", "X-Forwarded-For", hops=1) == "198.51.100.9"
    # the client wrote 1.1.1.1 itself; trusting 2 hops is a config choice, not a client one
    assert client_ip(h, "10.0.0.1", "X-Forwarded-For", hops=2) == "1.1.1.1"
    # no header configured: the socket peer; X-Real-IP / XFF from the client are ignored
    assert client_ip(h, "10.0.0.1", None) == "10.0.0.1"
    with pytest.raises(ClientAddressError):
        client_ip({}, "10.0.0.1", "X-Forwarded-For")
    with pytest.raises(ClientAddressError):
        client_ip({"X-Forwarded-For": "not-an-ip"}, "10.0.0.1", "X-Forwarded-For")
    with pytest.raises(ClientAddressError):
        client_ip({"Fly-Client-IP": "1.1.1.1, 2.2.2.2"}, None, "Fly-Client-IP")
    assert client_ip({"X-Forwarded-For": "[2001:db8::1]:443"}, None, "X-Forwarded-For") == (
        "2001:db8::1"
    )


def test_ipv6_keyed_by_64_and_mapped_v4():
    assert ip_key("2001:db8:1:2:aaaa::1") == ip_key("2001:db8:1:2:ffff:ffff:ffff:ffff")
    assert ip_key("2001:db8:1:2::1") != ip_key("2001:db8:1:3::1")
    assert ip_key("::ffff:198.51.100.9") == "198.51.100.9"
    s = b"k"
    assert hash_ip(s, "2001:db8:1:2::1") == hash_ip(s, "2001:db8:1:2:9::9")
    assert hash_ip(s, "198.51.100.9") != hash_ip(b"other", "198.51.100.9")
    assert hash_email(s, "A@Example.com ") == hash_email(s, "a@example.com")
    assert "198.51.100.9" not in hash_ip(s, "198.51.100.9")


def test_raw_ip_and_email_are_never_stored(tmp_path):
    svc, _ = service(tmp_path, script=[llm()])
    run(svc, req(email="secret.person@example.com"), ip="198.51.100.77")
    dump = "\n".join(sqlite3.connect(tmp_path / "ledger.sqlite").iterdump())
    assert "198.51.100.77" not in dump and "secret.person" not in dump


def test_ipv6_neighbours_share_a_budget(tmp_path):
    svc, fake = service(tmp_path, script=[llm()], ip_turn_cap=1)
    assert run(svc, req(), ip="2001:db8:1:2::1")["llm_called"] is True
    r = run(svc, req(), ip="2001:db8:1:2::beef")  # same /64, new address
    assert r["reply"]["reason"] == "ip_daily_cap" and r["budget"]["state"] == "paused"
    assert len(fake.calls) == 1


# --------------------------------------------------------------------------- service-level caps


def test_soft_cap_states_then_hard_stop(tmp_path):
    # price override: each fake answer (1500 in, 200 out tokens) costs 0.20 USD
    svc, fake = service(
        tmp_path, script=[llm()] * 14, price_in_per_mtok=100.0, price_out_per_mtok=250.0,
        max_output_tokens=200,
    )  # fmt: skip
    states = []
    for _ in range(14):
        r = run(svc, req())
        states.append((r["reply"]["kind"], r["budget"]["state"], r["budget"]["spent_today_usd"]))
    kinds = [s[0] for s in states]
    assert "ai_paused" in kinds
    assert any(s[1] == "near_soft_cap" for s in states)
    assert any(s[1] == "over_soft_cap" for s in states)
    assert max(s[2] for s in states) <= 2.0
    first_pause = kinds.index("ai_paused")
    assert all(k == "ai_paused" for k in kinds[first_pause:])
    assert states[first_pause][1] == "paused"


def test_global_cap_pauses_with_wallet_exhausted(tmp_path):
    svc, _ = service(
        tmp_path, script=[llm()] * 3, global_daily_usd=0.5,
        price_in_per_mtok=200.0, price_out_per_mtok=250.0, max_output_tokens=200,
    )  # fmt: skip
    run(svc, req())
    r = run(svc, req(), ip="198.51.100.200")
    assert r["reply"]["reason"] == "wallet_exhausted" and r["budget"]["wallet"] == "exhausted"


def test_turn_cap_per_ip(tmp_path):
    svc, fake = service(tmp_path, script=[llm()] * 5, ip_turn_cap=3)
    out = [run(svc, req()) for _ in range(4)]
    assert [o["budget"]["turns_today"] for o in out[:3]] == [1, 2, 3]
    assert out[2]["budget"]["state"] == "paused"  # the cap is reached: next turns pause
    assert out[3]["reply"]["reason"] == "ip_daily_cap" and len(fake.calls) == 3


def test_conversation_cap(tmp_path):
    svc, fake = service(tmp_path, script=[llm()] * (MAX_TURNS_PER_CONVERSATION + 2))
    cid = None
    for _ in range(MAX_TURNS_PER_CONVERSATION):
        r = run(svc, req(conversation_id=cid))
        cid = r["conversation_id"]
        assert r["reply"]["kind"] == "clarify"
    r = run(svc, req(conversation_id=cid))
    assert r["reply"]["reason"] == "conversation_cap" and r["llm_called"] is False
    assert len(fake.calls) == MAX_TURNS_PER_CONVERSATION


def test_email_is_required_before_ai_use():
    from pydantic import ValidationError

    from app.chat.contracts import ChatRequest

    with pytest.raises(ValidationError):
        ChatRequest.model_validate({**req().model_dump(), "email": None})
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({**req().model_dump(), "email": "not-an-email"})


def test_provider_down_pauses_without_charge(tmp_path):
    svc, fake = service(tmp_path, script=[ProviderError("gemini HTTP 503")])
    r = run(svc, req())
    assert r["reply"]["reason"] == "provider_unavailable" and r["llm_called"] is False
    assert r["budget"]["spent_today_usd"] == 0


def test_provider_timeout_is_charged_conservatively(tmp_path):
    svc, fake = service(tmp_path, script=[ProviderError("timeout", maybe_billed=True)])
    r = run(svc, req())
    assert r["reply"]["reason"] == "provider_unavailable" and r["budget"]["spent_today_usd"] > 0


def test_invalid_then_provider_down_is_llm_invalid(tmp_path):
    svc, fake = service(tmp_path, script=["not json", ProviderError("HTTP 500")])
    r = run(svc, req())
    assert r["reply"]["kind"] == "llm_invalid" and r["llm_called"] is True


def test_llm_invalid_after_two_bad_outputs(tmp_path):
    svc, fake = service(tmp_path, script=["{", "[]"])
    r = run(svc, req())
    assert r["reply"] == {
        "kind": "llm_invalid", "message_key": "ai.output_invalid", "browse_prices_available": True
    }  # fmt: skip
    assert len(fake.calls) == 2


def test_no_key_means_paused_not_crash(tmp_path):
    from app.chat.service import ChatService

    from .util import content, settings

    svc = ChatService(settings(tmp_path), content(), client=None, clock=lambda: NOW)
    assert run(svc, req())["reply"]["reason"] == "provider_unavailable"
