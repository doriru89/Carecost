"""Trace a pack row back to its source (brief O item 2).

* **Hospital file**: pack ``stage_row`` -> the staged leaf (``staging/<source>/<sha>.parquet``,
  for its ``item_ordinal``) -> the **raw file** in the A3 raw store
  (``raw/store/<source>/<sha>.<ext>``), opened independently of the ETL reader:
  CSV: the physical line (tall: ``stage_row + 4``; wide: ``item_ordinal + 4``; header = 3 lines),
  checked to contain the code and the amount; JSON: ``standard_charge_information[i]
  .standard_charges[j].payers_information[k]``, found by payer, plan and amount.
* **Insurer TiC file**: pack ``stage_row`` -> A2's ``prices.parquet`` (the raw
  ``negotiated_prices`` object, ``negotiated_rate`` kept as the raw JSON text), ``items.parquet``
  (the in-network item's byte span in the inflated JSON), ``rate_row.parquet`` + ``groups.parquet``
  (the provider group's TIN, name and NPI count). The raw ``.json.gz`` files are not kept on disk
  after staging (only ``*.fetch.json`` / ``*.headers``), so a TiC quote is the staged copy of the
  raw object plus the byte span to re-check it against a fresh download.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.quote.store import RateStore, Row

A3 = Path("/Users/austin/carecost-data/a7r")
DEFAULT_RAW = A3 / "raw" / "store"
DEFAULT_STAGING = A3 / "intermediate" / "staging"
DEFAULT_TIC = Path("/Users/austin/carecost-data/a7r/intermediate/tic")
CSV_HEADER_LINES = 3


@dataclass
class Trace:
    pointer: str  # file + line / JSON path / in-network item
    quote: str  # the raw text (hospital) or the staged raw object (TiC)
    verified: str  # raw_line | raw_json | staged_tic (raw gz not retained) | not_found


def _num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").replace("$", ""))
    except ValueError:
        return None


class Tracer:
    def __init__(self, store: RateStore, raw_root: Path = DEFAULT_RAW,
                 staging_root: Path = DEFAULT_STAGING, tic_root: Path = DEFAULT_TIC) -> None:  # fmt: skip
        self.store = store
        self.raw_root = raw_root
        self.staging_root = staging_root
        self.tic_root = tic_root

    # ------------------------------------------------------------------ batch entry

    def trace_all(
        self, rows: list[Row], values: dict[str, float] | None = None
    ) -> dict[str, Trace]:
        """``values``: uid -> the number the line used (a payer amount or the cash price), so the
        raw cell is matched on that number only."""
        self.values = values or {}
        by_src: dict[str, list[Row]] = defaultdict(list)
        for r in rows:
            by_src[r.source_id].append(r)
        out: dict[str, Trace] = {}
        for sid, rs in sorted(by_src.items()):
            kind = self.store.sources[sid].source_kind
            if kind == "insurer_tic":
                out.update(self._tic(sid, rs))
            elif kind == "hospital_mrf":
                out.update(self._hospital(sid, rs))
        return out

    # ------------------------------------------------------------------ TiC

    def _tic(self, sid: str, rows: list[Row]) -> dict[str, Trace]:
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        meta = self.store.sources[sid]
        d = self.tic_root / sid
        cur = (d / "CURRENT").read_text().strip() if (d / "CURRENT").exists() else ""
        run = d / cur
        if not cur or not (run / "prices.parquet").exists():
            return {r.uid: Trace(f"{meta.source_file} stage_row {r.stage_row}", "",
                                 "not_found") for r in rows}  # fmt: skip
        stages = sorted({r.stage_row for r in rows})
        prices = pq.read_table(run / "prices.parquet",
                               filters=[("stage_row", "in", stages)]).to_pylist()  # fmt: skip
        pmap = {p["stage_row"]: p for p in prices}
        rr = pq.read_table(run / "rate_row.parquet", columns=[
            "stage_row", "entity_id", "tic_provider_group_id", "tic_business_name",
            "tic_npi_count", "tic_tin_value"], filters=[("stage_row", "in", stages)]).to_pylist()  # fmt: skip
        rmap: dict[int, list[dict]] = defaultdict(list)
        for x in rr:
            rmap[x["stage_row"]].append(x)
        items = pq.read_table(run / "items.parquet").to_pylist()
        imap = {i["item_ordinal"]: i for i in items}
        if not imap:
            idx = pq.read_table(run / "index.items.parquet")
            ords = sorted({p["item_ordinal"] for p in prices})
            idx = idx.filter(pc.is_in(idx["ordinal"], value_set=__import__("pyarrow").array(ords)))
            imap = {i["ordinal"]: i for i in idx.to_pylist()}
        out = {}
        for r in rows:
            p = pmap.get(r.stage_row)
            if p is None:
                out[r.uid] = Trace(f"{meta.source_file} stage_row {r.stage_row}", "", "not_found")
                continue
            it = imap.get(p["item_ordinal"], {})
            grp = [x for x in rmap.get(r.stage_row, []) if x["entity_id"].endswith(r.tin)]
            g = grp[0] if grp else {}
            pointer = (
                f"{meta.source_file} (sha256 {meta.source_sha256[:12]}) in_network[{p['item_ordinal']}]"
                f" billing_code {p['billing_code']} bytes {it.get('raw_start')}-{it.get('raw_end')}"
                f" -> negotiated_rates[{p['rate_group_ordinal']}].negotiated_prices"
                f"[{p['price_ordinal']}]; provider_group {g.get('tic_provider_group_id')}"
                f" tin {g.get('tic_tin_value') or r.tin} ({g.get('tic_npi_count')} NPIs)"
            )
            obj = {
                "negotiated_type": p["negotiated_type"],
                "negotiated_rate": p["negotiated_rate"],
                "expiration_date": p["expiration_date"],
                "service_code": p["service_code"],
                "billing_class": p["billing_class"],
                "setting": p["setting"],
                "billing_code_modifier": p["billing_code_modifier"],
            }
            quote = (f'{json.dumps(obj, separators=(",", ":"))} | provider "{g.get("tic_business_name") or r.business_name}"'
                     f" | item {it.get('name') or ''!r}")  # fmt: skip
            out[r.uid] = Trace(pointer, quote, "staged_tic")
        return out

    # ------------------------------------------------------------------ hospital

    def _staged(self, sid: str, sha: str, stages: list[int]) -> dict[int, dict[str, Any]]:
        import pyarrow.parquet as pq

        f = self.staging_root / sid / f"{sha}.parquet"
        if not f.exists():
            return {}
        t = pq.read_table(f, filters=[("stage_row", "in", stages)])
        return {x["stage_row"]: x for x in t.to_pylist()}

    def _raw_path(self, sid: str) -> Path | None:
        meta = self.store.sources[sid]
        p = self.raw_root / sid / meta.source_file
        return p if p.exists() else None

    @staticmethod
    def _decode(b: bytes) -> str:
        try:
            return b.decode("utf-8")
        except UnicodeDecodeError:  # some hospital CSVs are Windows-1252 (0x92 = right quote)
            return b.decode("cp1252", errors="replace")

    def _open_text(self, p: Path) -> Iterator[str]:
        """Physical lines of the raw CSV (BOM stripped), each decoded on its own."""
        if p.suffix == ".zip":
            z = zipfile.ZipFile(p)
            name = next(n for n in z.namelist() if n.lower().endswith((".csv", ".json")))
            fh: Any = z.open(name)
        else:
            fh = p.open("rb")
        with fh:
            for i, b in enumerate(fh):
                if i == 0 and b.startswith(b"\xef\xbb\xbf"):
                    b = b[3:]
                yield self._decode(b)

    def _is_json(self, p: Path) -> bool:
        if p.suffix == ".json":
            return True
        if p.suffix == ".zip":
            return any(n.lower().endswith(".json") for n in zipfile.ZipFile(p).namelist())
        return False

    def _hospital(self, sid: str, rows: list[Row]) -> dict[str, Trace]:
        meta = self.store.sources[sid]
        raw = self._raw_path(sid)
        staged = self._staged(sid, meta.source_sha256, sorted({r.stage_row for r in rows}))
        if raw is None:
            return {r.uid: Trace(f"{meta.source_file} stage_row {r.stage_row}", "",
                                 "not_found") for r in rows}  # fmt: skip
        if self._is_json(raw):
            return self._hospital_json(sid, raw, rows, staged)
        return self._hospital_csv(sid, raw, rows, staged)

    def _hospital_csv(self, sid: str, raw: Path, rows: list[Row],
                      staged: dict[int, dict]) -> dict[str, Trace]:  # fmt: skip
        meta = self.store.sources[sid]
        want: dict[int, list[Row]] = defaultdict(list)
        lines_for: dict[str, list[int]] = {}
        for r in rows:
            st = staged.get(r.stage_row, {})
            cands = [r.stage_row + CSV_HEADER_LINES + 1]
            if st.get("item_ordinal") is not None:
                cands.append(int(st["item_ordinal"]) + CSV_HEADER_LINES + 1)
            lines_for[r.uid] = cands
            for c in cands:
                want[c].append(r)
        header: list[str] = []
        got: dict[int, str] = {}
        for n, text in enumerate(self._open_text(raw), start=1):
            if n == CSV_HEADER_LINES:
                header = next(csv.reader([text]))
            if n in want:
                got[n] = text.rstrip("\r\n")
            if n > max(want, default=0):
                break
        out = {}
        for r in rows:
            tr = None
            for n in lines_for[r.uid]:
                text = got.get(n)
                if text is None or r.code not in text:
                    continue
                cells = next(csv.reader([text]))
                if not self._amount_in(r, cells):
                    continue
                wide = len(cells) > 40  # CMS v3 wide: one column group per payer | plan
                quote = self._wide_quote(header, cells, r) if wide else text
                tr = Trace(f"{meta.source_file} (sha256 {meta.source_sha256[:12]}) line {n}",
                           quote, "raw_line")  # fmt: skip
                break
            out[r.uid] = tr or Trace(f"{meta.source_file} stage_row {r.stage_row} (line "
                                     f"{lines_for[r.uid][0]} did not match)", "", "not_found")  # fmt: skip
        return out

    def _targets(self, r: Row) -> list[float]:
        if r.uid in getattr(self, "values", {}):
            return [self.values[r.uid]]
        vals = [r.amount, r.discounted_cash, r.negotiated_pct]
        return [v for v in vals if v is not None]

    def _amount_in(self, r: Row, cells: list[str]) -> bool:
        nums = [x for c in cells if (x := _num(c)) is not None]
        for t in self._targets(r):
            if any(abs(x - t) <= max(0.011, 0.0005 * t) for x in nums):
                return True
        return not self._targets(r)

    def _wide_quote(self, header: list[str], cells: list[str], r: Row) -> str:
        """A wide CSV row as header=value pairs: the description and codes, every cell whose
        number is the traced amount (the payer|plan column that priced the line), then gross and
        cash."""
        targets = self._targets(r)
        first, hits, tail = [], [], []
        for h, c in zip(header, cells):
            if not c:
                continue
            hl = h.lower()
            x = _num(c)
            if hl.startswith(("description", "code|")):
                first.append(f"{h}={c}")
            elif x is not None and any(abs(x - t) <= max(0.011, 0.0005 * t) for t in targets):
                hits.append(f"{h}={c}")
            elif hl in ("standard_charge|gross", "standard_charge|discounted_cash"):
                tail.append(f"{h}={c}")
        return "; ".join(first + hits + tail)

    def _hospital_json(self, sid: str, raw: Path, rows: list[Row],
                       staged: dict[int, dict]) -> dict[str, Trace]:  # fmt: skip
        import ijson

        meta = self.store.sources[sid]
        want: dict[int, list[Row]] = defaultdict(list)
        for r in rows:
            st = staged.get(r.stage_row)
            if st is not None:
                want[int(st["item_ordinal"])].append(r)
        out: dict[str, Trace] = {}
        if want:
            fh = zipfile.ZipFile(raw).open(next(n for n in zipfile.ZipFile(raw).namelist()
                                                if n.endswith(".json"))) \
                if raw.suffix == ".zip" else raw.open("rb")  # fmt: skip
            head = fh.read(3)
            data = io.BufferedReader(_Prefixed(b"" if head == b"\xef\xbb\xbf" else head, fh))
            last = max(want)
            for i, item in enumerate(ijson.items(data, "standard_charge_information.item",
                                                 use_float=True)):  # fmt: skip
                if i in want:
                    for r in want[i]:
                        out[r.uid] = self._json_find(meta, i, item, r, staged[r.stage_row])
                if i >= last:
                    break
            fh.close()
        for r in rows:
            out.setdefault(r.uid, Trace(f"{meta.source_file} stage_row {r.stage_row}", "",
                                        "not_found"))  # fmt: skip
        return out

    def _json_find(self, meta, i: int, item: dict, r: Row, st: dict) -> Trace:
        for j, ch in enumerate(item.get("standard_charges") or []):
            payers = ch.get("payers_information") or []
            if r.row_kind == "chargemaster" or (r.discounted_cash is not None and not payers):
                pass
            for k, p in enumerate(payers):
                if (str(p.get("payer_name", "")).strip() == (st.get("payer_name") or "").strip()
                        and str(p.get("plan_name", "")).strip() == (st.get("plan_name") or "").strip()):  # fmt: skip
                    vals = [p.get("standard_charge_dollar"), p.get("estimated_amount"),
                            p.get("standard_charge_percentage")]  # fmt: skip
                    if any(v is not None and any(abs(float(v) - t) <= 0.011
                                                 for t in self._targets(r)) for v in vals):  # fmt: skip
                        ctx = {k2: ch.get(k2) for k2 in ("setting", "billing_class", "modifier_code",
                                                         "gross_charge", "discounted_cash") if k2 in ch}  # fmt: skip
                        quote = json.dumps({"payers_information": [p],
                                            "description": item.get("description"), **ctx,
                                            "code_information": item.get("code_information")},
                                           separators=(",", ":"), default=str)  # fmt: skip
                        return Trace(
                            f"{meta.source_file} (sha256 {meta.source_sha256[:12]}) "
                            f"standard_charge_information[{i}].standard_charges[{j}]"
                            f".payers_information[{k}]", quote[:1200], "raw_json")  # fmt: skip
            if r.payer_id is None or r.discounted_cash is not None:
                if ch.get("discounted_cash") is not None and any(
                        abs(float(ch["discounted_cash"]) - t) <= 0.011 for t in self._targets(r)):  # fmt: skip
                    ctx = {k2: ch.get(k2) for k2 in ("setting", "billing_class", "gross_charge",
                                                     "discounted_cash") if k2 in ch}  # fmt: skip
                    quote = json.dumps({"description": item.get("description"),
                                        "code_information": item.get("code_information"), **ctx},
                                       separators=(",", ":"), default=str)  # fmt: skip
                    return Trace(f"{meta.source_file} (sha256 {meta.source_sha256[:12]}) "
                                 f"standard_charge_information[{i}].standard_charges[{j}]",
                                 quote[:1200], "raw_json")  # fmt: skip
        return Trace(f"{meta.source_file} standard_charge_information[{i}] (no payer match)", "",
                     "not_found")  # fmt: skip


class _Prefixed(io.RawIOBase):
    """A binary stream with a few already-read bytes put back in front."""

    def __init__(self, prefix: bytes, fh: Any) -> None:
        self.prefix = prefix
        self.fh = fh

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        if self.prefix:
            n = min(len(b), len(self.prefix))
            b[:n] = self.prefix[:n]
            self.prefix = self.prefix[n:]
            return n
        data = self.fh.read(len(b))
        b[: len(data)] = data
        return len(data)
