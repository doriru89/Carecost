"""Seekable inflate for gzip / zip TiC files (zlib's ``zran`` technique, through ctypes).

Why: a TiC in-network file is one JSON object of 1-190 GB, gzipped. Python's ``zlib`` module
cannot report deflate *block boundaries* or resume mid-stream, so it cannot build a seek index.
The system zlib can (``inflate(Z_BLOCK)``, ``inflatePrime``, ``inflateSetDictionary``), so this
module calls it directly.

* :class:`InflatePass` inflates a whole file in one sequential pass (local file or HTTP stream),
  yields ``(raw_offset, bytes)`` and records a :class:`Checkpoint` about every ``span`` raw bytes.
  A checkpoint is a deflate block boundary plus the 32 KiB of output before it.
* :func:`read_raw_range` re-inflates ``[raw_a, raw_b)`` starting at the nearest checkpoint,
  pulling compressed bytes from any ``fetch(comp_a, comp_b)`` callable (a local file, or HTTP
  Range through ``fetch.http_range``).

Containers: gzip (multi-member allowed, CRC32 + ISIZE verified per member) and zip (the first
local file entry, method 8). Decompressed bytes are capped (``max_raw``) so a gzip bomb fails
loudly instead of running forever.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import struct
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

WINDOW = 32768
OUT_CHUNK = 1 << 22  # 4 MiB of output per inflate() call at most

Z_OK, Z_STREAM_END, Z_NEED_DICT, Z_BUF_ERROR = 0, 1, 2, -5
Z_BLOCK = 5


class InflateError(RuntimeError):
    pass


class DecompressCapExceeded(InflateError):
    pass


class _ZStream(ctypes.Structure):
    _fields_ = [
        ("next_in", ctypes.c_void_p),
        ("avail_in", ctypes.c_uint),
        ("total_in", ctypes.c_ulong),
        ("next_out", ctypes.c_void_p),
        ("avail_out", ctypes.c_uint),
        ("total_out", ctypes.c_ulong),
        ("msg", ctypes.c_char_p),
        ("state", ctypes.c_void_p),
        ("zalloc", ctypes.c_void_p),
        ("zfree", ctypes.c_void_p),
        ("opaque", ctypes.c_void_p),
        ("data_type", ctypes.c_int),
        ("adler", ctypes.c_ulong),
        ("reserved", ctypes.c_ulong),
    ]


def _load_zlib() -> ctypes.CDLL:
    name = ctypes.util.find_library("z") or "libz.so.1"
    lib = ctypes.CDLL(name)
    lib.zlibVersion.restype = ctypes.c_char_p
    lib.inflateInit2_.argtypes = [
        ctypes.POINTER(_ZStream),
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    lib.inflate.argtypes = [ctypes.POINTER(_ZStream), ctypes.c_int]
    lib.inflateEnd.argtypes = [ctypes.POINTER(_ZStream)]
    lib.inflatePrime.argtypes = [ctypes.POINTER(_ZStream), ctypes.c_int, ctypes.c_int]
    lib.inflateSetDictionary.argtypes = [ctypes.POINTER(_ZStream), ctypes.c_char_p, ctypes.c_uint]
    return lib


_Z = _load_zlib()
_ZVER = _Z.zlibVersion()


@dataclass(frozen=True)
class Checkpoint:
    """Resume point: ``comp_off`` is the absolute file offset of the next unread compressed byte;
    when ``bits`` > 0 the top ``bits`` bits of byte ``comp_off - 1`` belong to the next block."""

    raw_off: int
    comp_off: int
    bits: int
    prime_byte: int  # byte at comp_off - 1 (0 when bits == 0)
    window: bytes  # up to 32 KiB of raw output before raw_off
    member: int  # gzip member number (0-based)


class _RawInflater:
    """One raw-deflate stream (wbits = -15)."""

    def __init__(self) -> None:
        self.z = _ZStream()
        rc = _Z.inflateInit2_(ctypes.byref(self.z), -15, _ZVER, ctypes.sizeof(_ZStream))
        if rc != Z_OK:
            raise InflateError(f"inflateInit2 failed: {rc}")
        self.out = ctypes.create_string_buffer(OUT_CHUNK)
        self._in: ctypes.Array[ctypes.c_char] | None = None
        self._in_len = 0
        self.closed = False
        self._prev_last = -1

    def prime(self, bits: int, value: int) -> None:
        if bits and _Z.inflatePrime(ctypes.byref(self.z), bits, value) != Z_OK:
            raise InflateError("inflatePrime failed")

    def set_dictionary(self, window: bytes) -> None:
        if window and _Z.inflateSetDictionary(ctypes.byref(self.z), window, len(window)) != Z_OK:
            raise InflateError("inflateSetDictionary failed")

    def feed(self, data: bytes) -> None:
        assert self.z.avail_in == 0
        if self._in is not None and self._in_len:
            self._prev_last = ctypes.string_at(ctypes.addressof(self._in) + self._in_len - 1, 1)[0]
        self._in = ctypes.create_string_buffer(data, len(data))
        self._in_len = len(data)
        self.z.next_in = ctypes.addressof(self._in)
        self.z.avail_in = len(data)

    @property
    def avail_in(self) -> int:
        return int(self.z.avail_in)

    def unconsumed(self) -> bytes:
        n = self.avail_in
        if not n or self._in is None:
            return b""
        return ctypes.string_at(ctypes.addressof(self._in) + self._in_len - n, n)

    def last_consumed_byte(self) -> int:
        """The byte just before next_in (for inflatePrime when resuming)."""
        assert self._in is not None
        pos = self._in_len - self.avail_in
        return (
            ctypes.string_at(ctypes.addressof(self._in) + pos - 1, 1)[0] if pos else self._prev_last
        )

    def step(self) -> tuple[int, bytes, int]:
        """One inflate(Z_BLOCK) call -> (rc, output, data_type)."""
        self.z.next_out = ctypes.addressof(self.out)
        self.z.avail_out = OUT_CHUNK
        rc = _Z.inflate(ctypes.byref(self.z), Z_BLOCK)
        if rc not in (Z_OK, Z_STREAM_END, Z_BUF_ERROR):
            msg = self.z.msg.decode() if self.z.msg else ""
            raise InflateError(f"inflate error {rc} {msg}")
        produced = OUT_CHUNK - int(self.z.avail_out)
        return (
            rc,
            (ctypes.string_at(self.out, produced) if produced else b""),
            int(self.z.data_type),
        )

    def close(self) -> None:
        if not self.closed:
            _Z.inflateEnd(ctypes.byref(self.z))
            self.closed = True

    def __del__(self) -> None:  # pragma: no cover - GC safety net
        try:
            self.close()
        except Exception:
            pass


class ByteSource:
    """Sequential reader over an iterable of byte chunks with an absolute position and
    push-back, used for both full streams and range reads."""

    def __init__(self, chunks: Iterable[bytes], start: int = 0) -> None:
        self._it: Iterator[bytes] = iter(chunks)
        self._pending = b""
        self.pos = start  # absolute offset of the next byte read() returns

    def read(self, n: int = -1) -> bytes:
        """Up to n bytes (n < 0: the next chunk). b'' only at EOF."""
        if not self._pending:
            for chunk in self._it:
                if chunk:
                    self._pending = chunk
                    break
            else:
                return b""
        if n < 0 or n >= len(self._pending):
            out, self._pending = self._pending, b""
        else:
            out, self._pending = self._pending[:n], self._pending[n:]
        self.pos += len(out)
        return out

    def read_exact(self, n: int) -> bytes:
        parts, got = [], 0
        while got < n:
            b = self.read(n - got)
            if not b:
                raise InflateError(f"unexpected EOF at {self.pos} (wanted {n - got} more bytes)")
            parts.append(b)
            got += len(b)
        return b"".join(parts)

    def unread(self, data: bytes) -> None:
        if data:
            self._pending = data + self._pending
            self.pos -= len(data)

    def read_until_nul(self) -> bytes:
        out = bytearray()
        while True:
            b = self.read_exact(1)
            if b == b"\x00":
                return bytes(out)
            out += b


def _gzip_header(src: ByteSource) -> bool:
    """Consume one gzip member header. False at clean EOF (or trailing zero padding)."""
    first = src.read(1)
    if not first:
        return False
    if first == b"\x00":  # some writers pad with zeros after the last member
        while True:
            b = src.read()
            if not b:
                return False
            if b.strip(b"\x00"):
                raise InflateError("garbage after the last gzip member")
    rest = src.read_exact(9)
    hdr = first + rest
    if hdr[:2] != b"\x1f\x8b" or hdr[2] != 8:
        raise InflateError(f"not a gzip member at offset {src.pos - 10}")
    flg = hdr[3]
    if flg & 4:  # FEXTRA
        (xlen,) = struct.unpack("<H", src.read_exact(2))
        src.read_exact(xlen)
    if flg & 8:
        src.read_until_nul()
    if flg & 16:
        src.read_until_nul()
    if flg & 2:
        src.read_exact(2)
    return True


def _zip_header(src: ByteSource) -> tuple[str, int]:
    """Consume the first zip local file header -> (member name, method)."""
    h = src.read_exact(30)
    sig, _ver, _flag, method, _t, _d, _crc, _cs, _us, nlen, xlen = struct.unpack("<IHHHHHIIIHH", h)
    if sig != 0x04034B50:
        raise InflateError("not a zip local file header")
    name = src.read_exact(nlen).decode("utf-8", "replace")
    src.read_exact(xlen)
    if method != 8:
        raise InflateError(f"zip member {name}: compression method {method} is not deflate")
    return name, method


@dataclass
class PassStats:
    comp_bytes: int = 0
    raw_bytes: int = 0
    members: int = 0
    checkpoints: int = 0
    zip_member: str = ""


class InflatePass:
    """Inflate a whole container sequentially. Iterate to get ``(raw_offset, data)``;
    ``checkpoints`` fills as it goes. ``max_raw`` caps decompressed bytes."""

    def __init__(
        self,
        chunks: Iterable[bytes],
        container: str,
        span: int = 16 << 20,
        max_raw: int | None = None,
        verify_crc: bool = True,
        on_checkpoint: Callable[[Checkpoint], None] | None = None,
        coalesce: int = 1 << 22,
    ) -> None:
        self.coalesce = coalesce
        if container not in ("gzip", "zip"):
            raise ValueError(f"unsupported container {container!r}")
        self.src = ByteSource(chunks)
        self.container = container
        self.span = span
        self.max_raw = max_raw
        self.verify_crc = verify_crc
        self.checkpoints: list[Checkpoint] = []
        self.on_checkpoint = on_checkpoint
        self.stats = PassStats()

    def _checkpoint(self, inf: _RawInflater, raw: int, tail: bytes, member: int, base: int) -> None:
        bits = inf.z.data_type & 7
        comp_off = base + int(inf.z.total_in)
        prime = inf.last_consumed_byte() if bits else 0
        cp = Checkpoint(raw, comp_off, bits, max(prime, 0), tail[-WINDOW:], member)
        self.checkpoints.append(cp)
        if self.on_checkpoint:
            self.on_checkpoint(cp)

    def __iter__(self) -> Iterator[tuple[int, bytes]]:
        """Coalesced output: chunks of at least ``coalesce`` bytes (the last may be shorter)."""
        acc: list[bytes] = []
        acc_off = 0
        acc_len = 0
        for off, data in self._blocks():
            if not acc:
                acc_off = off
            acc.append(data)
            acc_len += len(data)
            if acc_len >= self.coalesce:
                yield acc_off, b"".join(acc)
                acc, acc_len = [], 0
        if acc:
            yield acc_off, b"".join(acc)

    def _blocks(self) -> Iterator[tuple[int, bytes]]:
        raw = 0
        tail = b""
        last_cp = None
        member = 0
        src = self.src
        while True:
            if self.container == "gzip":
                if not _gzip_header(src):
                    break
            else:
                if member:
                    break
                self.stats.zip_member, _ = _zip_header(src)
            inf = _RawInflater()
            base = src.pos  # absolute offset of this member's first deflate byte
            if member == 0 or last_cp is None or raw - last_cp >= self.span:
                cp = Checkpoint(raw, base, 0, 0, b"", member)  # a fresh deflate stream: no window
                self.checkpoints.append(cp)
                if self.on_checkpoint:
                    self.on_checkpoint(cp)
                last_cp = raw
            crc = 0
            member_raw = 0
            ended = False
            try:
                while not ended:
                    if inf.avail_in == 0:
                        data = src.read(1 << 20)
                        if not data:
                            raise InflateError(f"truncated deflate stream in member {member}")
                        inf.feed(data)
                    while True:
                        rc, out, dtype = inf.step()
                        if out:
                            yield raw, out
                            raw += len(out)
                            member_raw += len(out)
                            if self.verify_crc:
                                crc = zlib.crc32(out, crc)
                            tail = (tail + out)[-WINDOW:] if len(out) < WINDOW else out[-WINDOW:]
                            if self.max_raw is not None and raw > self.max_raw:
                                raise DecompressCapExceeded(
                                    f"decompressed bytes exceed the cap of {self.max_raw:,}"
                                )
                        if rc == Z_STREAM_END:
                            ended = True
                            break
                        if (dtype & 128) and not (dtype & 64):
                            if last_cp is None or raw - last_cp >= self.span:
                                self._checkpoint(inf, raw, tail, member, base)
                                last_cp = raw
                        if rc == Z_BUF_ERROR or (inf.avail_in == 0 and not out):
                            break
                left = inf.unconsumed()
            finally:
                inf.close()
            src.unread(left)
            if self.container == "gzip":
                crc_file, isize = struct.unpack("<II", src.read_exact(8))
                if self.verify_crc and crc_file != (crc & 0xFFFFFFFF):
                    raise InflateError(f"CRC mismatch in gzip member {member}")
                if isize != member_raw & 0xFFFFFFFF:
                    raise InflateError(f"ISIZE mismatch in gzip member {member}")
            member += 1
        self.stats.comp_bytes = src.pos
        self.stats.raw_bytes = raw
        self.stats.members = member
        self.stats.checkpoints = len(self.checkpoints)


Fetch = Callable[[int, int], bytes]  # (comp_a, comp_b_exclusive) -> bytes


def _ranged_chunks(fetch: Fetch, start: int, end: int | None, step: int) -> Iterator[bytes]:
    pos = start
    while end is None or pos < end:
        hi = pos + step if end is None else min(pos + step, end)
        data = fetch(pos, hi)
        if not data:
            return
        yield data
        short = len(data) < hi - pos
        pos += len(data)
        if short:  # EOF
            return


def read_raw_range(
    checkpoints: list[Checkpoint],
    raw_a: int,
    raw_b: int,
    fetch: Fetch,
    container: str,
    comp_size: int,
    step: int = 1 << 20,
) -> bytes:
    """Raw bytes ``[raw_a, raw_b)`` re-inflated from the nearest checkpoint at or before raw_a.

    Compressed bytes are pulled lazily in ``step``-sized ranges, so the cost is about
    (raw_b - checkpoint.raw_off) / ratio compressed bytes. Crossing gzip member boundaries works.
    """
    if raw_b <= raw_a:
        return b""
    cps = [c for c in checkpoints if c.raw_off <= raw_a]
    if not cps:
        raise InflateError(f"no checkpoint at or before raw offset {raw_a}")
    cp = max(cps, key=lambda c: c.raw_off)
    src = ByteSource(_ranged_chunks(fetch, cp.comp_off, comp_size, step), start=cp.comp_off)
    raw = cp.raw_off
    parts: list[bytes] = []
    first = True
    while raw < raw_b:
        inf = _RawInflater()
        try:
            if first:
                inf.prime(cp.bits, cp.prime_byte >> (8 - cp.bits) if cp.bits else 0)
                inf.set_dictionary(cp.window)
                first = False
            ended = False
            while not ended and raw < raw_b:
                if inf.avail_in == 0:
                    data = src.read(step)
                    if not data:
                        raise InflateError("compressed data ended before the requested range")
                    inf.feed(data)
                while raw < raw_b:
                    rc, out, _ = inf.step()
                    if out:
                        lo, hi = max(raw_a - raw, 0), min(raw_b - raw, len(out))
                        if lo < hi:
                            parts.append(out[lo:hi])
                        raw += len(out)
                    if rc == Z_STREAM_END:
                        ended = True
                        break
                    if rc == Z_BUF_ERROR or (inf.avail_in == 0 and not out):
                        break
            left = inf.unconsumed()
        finally:
            inf.close()
        if raw >= raw_b:
            break
        src.unread(left)
        if container != "gzip":
            raise InflateError("range runs past the end of the zip member")
        src.read_exact(8)  # trailer of the member we just finished
        if not _gzip_header(src):
            raise InflateError("range runs past the end of the file")
    return b"".join(parts)


def file_fetcher(path: str) -> Fetch:
    """Local-file equivalent of an HTTP Range fetch (for tests and local verification)."""

    def fetch(a: int, b: int) -> bytes:
        with open(path, "rb") as f:
            f.seek(a)
            return f.read(b - a)

    return fetch
