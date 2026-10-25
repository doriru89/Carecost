"""Byte-level structural scan of one decompressed TiC in-network JSON stream.

The file is one JSON object: a few header fields, ``provider_references`` (usually first) and
``in_network`` (a list of items, one per billing code). Parsing all of it is far too slow for
UHC (188 GB raw), so the scanner only *jumps* between item headers with ``bytes.find`` and
JSON-decodes the parts we keep:

* the header fields and the whole ``provider_references`` array (every provider group: TIN,
  NPIs, business name). Groups are never filtered here; the Boston cut happens downstream.
* every ``in_network`` item whose ``billing_code`` is in the target set (whole item, lossless:
  numbers are kept as their source text).

For every item (target or not) it records ``(raw_start, raw_end, billing_code_type,
billing_code, negotiation_arrangement)`` in the *item map*, which the seek index uses to
range-read a code later without a full pass.

Item headers are found by the first key of the first item (``"negotiation_arrangement"`` in
every 2026 file we have seen), requiring ``{`` before it and ``[`` or ``,`` before that. A
target item is only accepted when it decodes to an object with ``negotiated_rates``; a false
header inside an item makes the decode fail and the scan continues to the next header.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

_WS = b" \t\r\n"
_RE_CODE = re.compile(rb'"billing_code"\s*:\s*"((?:[^"\\]|\\.)*)"')
_RE_TYPE = re.compile(rb'"billing_code_type"\s*:\s*"((?:[^"\\]|\\.)*)"')
_RE_ARR = re.compile(rb'"negotiation_arrangement"\s*:\s*"((?:[^"\\]|\\.)*)"')
_RE_RATES = re.compile(rb'"negotiated_rates"\s*:')
_RE_PRICE = re.compile(rb'"negotiated_rate"\s*:')
_RE_FIRSTKEY = re.compile(rb'"in_network"\s*:\s*\[\s*\{\s*"([A-Za-z_]+)"')
HEADER_WINDOW = 1 << 16


class ScanError(RuntimeError):
    pass


def _loads(text: bytes | str) -> Any:
    """Lossless decode: floats keep their source text ("1243.2000")."""
    return json.loads(text, parse_float=str)


def _raw_decode(text: str) -> tuple[Any, int]:
    return json.JSONDecoder(parse_float=str).raw_decode(text)


@dataclass
class ItemRef:
    ordinal: int
    raw_start: int
    raw_end: int
    billing_code_type: str
    billing_code: str
    negotiation_arrangement: str


@dataclass
class TargetItem:
    ref: ItemRef
    obj: dict[str, Any]
    independent_prices: int  # count of "negotiated_rate": in the item's bytes


@dataclass
class ScanResult:
    header: dict[str, Any] = field(default_factory=dict)
    provider_references: list[dict[str, Any]] = field(default_factory=list)
    provider_references_span: tuple[int, int] = (0, 0)
    independent_groups: int = 0  # count of "tin": in the provider_references bytes
    items: list[ItemRef] = field(default_factory=list)
    item_key: str = ""
    raw_bytes: int = 0
    false_headers: int = 0
    undetermined_items: int = 0


def _rstrip_sep(buf: bytes | bytearray, end: int, lo: int) -> int:
    """End of the JSON value before a separator: skip whitespace and one ','."""
    i = end
    while i > lo and buf[i - 1] in _WS:
        i -= 1
    if i > lo and buf[i - 1] == 0x2C:  # ','
        i -= 1
    while i > lo and buf[i - 1] in _WS:
        i -= 1
    return i


def _is_header(buf: bytes | bytearray, kpos: int) -> int:
    """Start offset of the item object if the key at kpos opens an in_network item, else -1."""
    i = kpos
    while i > 0 and buf[i - 1] in _WS:
        i -= 1
    if i == 0 or buf[i - 1] != 0x7B:  # '{'
        return -1
    brace = i - 1
    j = brace
    while j > 0 and buf[j - 1] in _WS:
        j -= 1
    if j == 0 or buf[j - 1] not in (0x5B, 0x2C):  # '[' or ','
        return -1
    return brace


def _header_meta(buf: bytes | bytearray, start: int, stop: int) -> tuple[str, str, str] | None:
    """(code_type, code, arrangement) from an item header window, or None if the code is not
    found before ``negotiated_rates`` (then the item must be decoded to know its code)."""
    m_rates = _RE_RATES.search(buf, start, stop)
    lim = m_rates.start() if m_rates else stop
    m_code = _RE_CODE.search(buf, start, lim)
    if not m_code:
        return None
    m_type = _RE_TYPE.search(buf, start, lim)
    m_arr = _RE_ARR.search(buf, start, lim)
    dec = lambda m: _loads(b'"' + m.group(1) + b'"') if m else ""  # noqa: E731
    return dec(m_type), dec(m_code).strip(), dec(m_arr)


def scan(
    chunks: Iterable[tuple[int, bytes]], target_codes: set[str]
) -> Iterator[TargetItem | ScanResult]:
    """Yield each target item as it completes, then the :class:`ScanResult` last."""
    res = ScanResult()
    it = iter(chunks)
    buf = bytearray()
    base = 0  # raw offset of buf[0]
    eof = False

    def more() -> bool:
        nonlocal buf, eof
        for _off, data in it:
            buf += data
            res.raw_bytes += len(data)
            return True
        eof = True
        return False

    # ---- head: header fields + provider_references (if they come before in_network)
    while True:
        m = _RE_FIRSTKEY.search(buf)
        if m:
            break
        if not more():
            if b'"in_network"' in buf:
                m = None
                break
            raise ScanError("no in_network key found")
    i_in = buf.find(b'"in_network"')
    i_pr = buf.find(b'"provider_references"', 0, i_in)
    head_end = i_pr if i_pr >= 0 else i_in
    head_txt = buf[buf.find(b"{") + 1 : head_end].strip().rstrip(b",")
    res.header = _loads(b"{" + bytes(head_txt) + b"}") if head_txt else {}
    if i_pr >= 0:
        arr = buf.find(b"[", i_pr)
        end = _rstrip_sep(buf, i_in, arr)
        res.provider_references = _loads(bytes(buf[arr:end]))
        res.provider_references_span = (arr, end)
        res.independent_groups = len(re.findall(rb'"tin"\s*:', buf[arr:end]))
    if m is None:  # empty in_network
        res.item_key = ""
        yield res
        return
    if not res.provider_references and i_pr < 0:
        raise ScanError(
            "provider_references after in_network is not supported (no 2026 MA file does this)"
        )
    key = b'"' + m.group(1) + b'"'
    res.item_key = m.group(1).decode()

    # ---- in_network items. cur = (absolute start, meta, keep) of the open item.
    cur: tuple[int, tuple[str, str, str] | None, bool] | None = None
    pending: list[TargetItem] = []
    ordinal = 0
    pos = m.start(1) - 1  # buffer-relative search position for the next key

    def close(start_abs: int, meta: tuple[str, str, str] | None, keep: bool, stop: int) -> bool:
        """Close the open item at buffer offset ``stop``. False when a kept item does not
        decode there (the candidate header was false)."""
        nonlocal ordinal
        lo = max(start_abs - base, 0)
        end = _rstrip_sep(buf, stop, lo)
        obj = None
        if keep:
            try:
                obj = _loads(bytes(buf[lo:end]))
            except ValueError:
                return False
            if not isinstance(obj, dict) or "negotiated_rates" not in obj:
                return False
            if meta is None:
                meta = (
                    str(obj.get("billing_code_type", "")),
                    str(obj.get("billing_code", "")).strip(),
                    str(obj.get("negotiation_arrangement", "")),
                )
        ref = ItemRef(ordinal, start_abs, base + end, *(meta or ("", "", "")))
        ordinal += 1
        res.items.append(ref)
        if obj is not None and ref.billing_code in target_codes:
            pending.append(TargetItem(ref, obj, len(_RE_PRICE.findall(buf, lo, end))))
        return True

    margin = len(key) + 64
    while True:
        k = buf.find(key, pos)
        if k < 0:
            if eof:
                break
            if cur is not None and not cur[2]:  # skipping a non-target item: drop its bytes
                drop = len(buf) - margin
                if drop > 0:
                    del buf[:drop]
                    base += drop
            pos = max(len(buf) - len(key), 0)
            more()
            continue
        start = _is_header(buf, k)
        if start < 0:
            res.false_headers += 1
            pos = k + len(key)
            continue
        if not eof and len(buf) - start < HEADER_WINDOW and _RE_RATES.search(buf, k) is None:
            more()  # need the item header in the buffer to read its code
            continue
        if cur is not None:
            if not close(cur[0], cur[1], cur[2], start):
                res.false_headers += 1
                pos = k + len(key)
                continue
            yield from pending
            pending.clear()
        meta = _header_meta(buf, start, min(len(buf), start + HEADER_WINDOW))
        if meta is None:
            res.undetermined_items += 1
        keep = meta is None or meta[1] in target_codes
        del buf[:start]  # nothing before an item header is needed any more
        base += start
        pos = k - start + len(key)
        cur = (base, meta, keep)
    # ---- last item: decode it (kept) or find the end of in_network (skipped)
    if cur is not None:
        start_abs, meta, keep = cur
        lo = start_abs - base
        if keep and lo >= 0:
            text = bytes(buf[lo:]).decode("utf-8")
            try:
                _obj, n_chars = _raw_decode(text)
            except ValueError as e:
                raise ScanError(f"cannot decode the last in_network item: {e}") from e
            stop = lo + len(text[:n_chars].encode("utf-8"))
        else:
            stop = len(buf)
            for ch in (b"}", b"]"):
                while stop > 0 and buf[stop - 1] in _WS:
                    stop -= 1
                if stop == 0 or buf[stop - 1] != ch[0]:
                    raise ScanError("unexpected bytes after the last in_network item")
                stop -= 1
        if not close(start_abs, meta, keep, stop):
            raise ScanError("the last in_network item does not decode")
        yield from pending
        pending.clear()
    yield res
