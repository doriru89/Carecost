"""Stage 2: raw hospital MRF -> lossless Parquet (one row per leaf).

A *leaf* is one CSV data row (tall), one chargemaster row x payer|plan group (wide; a row
with no group values stays one leaf), or one JSON item x standard_charge x payer (a charge
without payers, or an item without charges, stays one leaf).

Rules: streaming only (csv over the zip stream, ijson for JSON); no code filter; no dedup;
every v3.0.0 field kept as the source text; unknown keys/columns go to ``extra`` (JSON).
Gate: staged rows == an independent leaf count, otherwise ``StageError`` and no output.
"""

from __future__ import annotations

import codecs
import csv
import io
import json
import time
import zipfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import IO, Any

import ijson
import pyarrow as pa
import pyarrow.parquet as pq

from app.etl.config import SourceSpec

csv.field_size_limit(2**31 - 1)

BATCH = 20_000

# Staged column order. Values are source text ("" when absent) except the ints.
VALUE_FIELDS = [
    "description",
    "modifiers",
    "setting",
    "billing_class",
    "drug_unit",
    "drug_type",
    "gross",
    "discounted_cash",
    "min",
    "max",
    "additional_generic_notes",
    "payer_name",
    "plan_name",
    "negotiated_dollar",
    "negotiated_percentage",
    "negotiated_algorithm",
    "estimated_amount",
    "median_amount",
    "p10",
    "p90",
    "count",
    "methodology",
    "additional_payer_notes",
]
SCHEMA = pa.schema(
    [
        pa.field("source_id", pa.string()),
        pa.field("source_sha256", pa.string()),
        pa.field("stage_row", pa.int64()),
        pa.field("item_ordinal", pa.int64()),
        pa.field("codes", pa.list_(pa.struct([("code", pa.string()), ("type", pa.string())]))),
        pa.field("code_values", pa.string()),  # "|11102|0761|PX-76002565|" for fast filtering
        *[pa.field(f, pa.string()) for f in VALUE_FIELDS],
        pa.field("extra", pa.string()),
    ]
)

# CMS v3 CSV header -> staged field
CSV_MAP = {
    "description": "description",
    "modifiers": "modifiers",
    "setting": "setting",
    "billing_class": "billing_class",
    "drug_unit_of_measurement": "drug_unit",
    "drug_type_of_measurement": "drug_type",
    "standard_charge|gross": "gross",
    "standard_charge|discounted_cash": "discounted_cash",
    "standard_charge|min": "min",
    "standard_charge|max": "max",
    "additional_generic_notes": "additional_generic_notes",
    "payer_name": "payer_name",
    "plan_name": "plan_name",
    "standard_charge|negotiated_dollar": "negotiated_dollar",
    "standard_charge|negotiated_percentage": "negotiated_percentage",
    "standard_charge|negotiated_algorithm": "negotiated_algorithm",
    "estimated_amount": "estimated_amount",
    "median_amount": "median_amount",
    "10th_percentile": "p10",
    "90th_percentile": "p90",
    "count": "count",
    "standard_charge|methodology": "methodology",
    "additional_payer_notes": "additional_payer_notes",
}
# wide-format per-group fields: standard_charge|<payer>|<plan>|<field> or <field>|<payer>|<plan>
WIDE_SC_FIELDS = {
    "negotiated_dollar": "negotiated_dollar",
    "negotiated_percentage": "negotiated_percentage",
    "negotiated_algorithm": "negotiated_algorithm",
    "methodology": "methodology",
    "estimated_amount": "estimated_amount",
}
WIDE_PREFIX_FIELDS = {
    "median_amount": "median_amount",
    "10th_percentile": "p10",
    "90th_percentile": "p90",
    "count": "count",
    "additional_payer_notes": "additional_payer_notes",
    "estimated_amount": "estimated_amount",
}
JSON_ITEM_KEYS = {"description", "code_information", "drug_information", "standard_charges"}
JSON_CHARGE_MAP = {
    "setting": "setting",
    "billing_class": "billing_class",
    "modifier_code": "modifiers",
    "gross_charge": "gross",
    "discounted_cash": "discounted_cash",
    "minimum": "min",
    "maximum": "max",
    "additional_generic_notes": "additional_generic_notes",
}
JSON_PAYER_MAP = {
    "payer_name": "payer_name",
    "plan_name": "plan_name",
    "standard_charge_dollar": "negotiated_dollar",
    "standard_charge_percentage": "negotiated_percentage",
    "standard_charge_algorithm": "negotiated_algorithm",
    "estimated_amount": "estimated_amount",
    "median_amount": "median_amount",
    "10th_percentile": "p10",
    "90th_percentile": "p90",
    "count": "count",
    "methodology": "methodology",
    "additional_payer_notes": "additional_payer_notes",
}
_SCI = "standard_charge_information.item"
_CHG = _SCI + ".standard_charges.item"
_PAY = _CHG + ".payers_information.item"


class StageError(RuntimeError):
    pass


def _next(reader: Iterator[list[str]], what: str) -> list[str]:
    """``next()`` that turns an early end of file into ``StageError`` (a truncated CSV header
    used to escape as a bare StopIteration and kill the whole ``stage`` run)."""
    try:
        return next(reader)
    except StopIteration:
        raise StageError(f"file ends before its {what} row (truncated?)") from None


def size_drop_error(
    source_id: str, cur_bytes: int, prev_bytes: int | None, max_drop_pct: float
) -> str | None:
    """Truncation signal: the new copy is much smaller than the previous copy of the same source."""
    if not prev_bytes or cur_bytes >= prev_bytes:
        return None
    drop = 1 - cur_bytes / prev_bytes
    if drop * 100 <= max_drop_pct:
        return None
    return (
        f"{source_id}: file is {drop:.0%} smaller than the previous copy ({prev_bytes:,} -> "
        f"{cur_bytes:,} bytes, limit {max_drop_pct:g}%): truncated? (stage --allow-shrink accepts it)"
    )


# ---------------------------------------------------------------------------- helpers

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d")


def parse_date(raw: str) -> date:
    """The four forms seen in 2026 files: 2026-03-27, 03/13/2026, 3/20/2026, 4/1/2026."""
    s = (raw or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised last_updated_on {raw!r}")


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "|".join(_text(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, default=str, sort_keys=True)
    return str(v)


def _dedup(xs: list[str]) -> list[str]:
    out: list[str] = []
    for x in xs:
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


def _open_binary(spec: SourceSpec, path: Path) -> tuple[IO[bytes], bool]:
    """Binary stream of the payload (first non-macOS member of a zip), BOM skipped."""
    if spec.container == "zip":
        zf = zipfile.ZipFile(path)
        names = [n for n in zf.namelist() if not n.startswith("__MACOSX") and not n.endswith("/")]
        if len(names) != 1:
            raise StageError(f"{path.name}: expected exactly one payload in zip, got {names}")
        raw: IO[bytes] = zf.open(names[0])
    else:
        raw = path.open("rb")
    br = io.BufferedReader(raw, buffer_size=1 << 20)  # type: ignore[arg-type,type-var]
    bom = br.peek(3)[:3] == codecs.BOM_UTF8
    if bom:
        br.read(3)
    return br, bom


def _text_stream(spec: SourceSpec, path: Path) -> tuple[io.TextIOWrapper, bool]:
    b, bom = _open_binary(spec, path)
    enc = "utf-8" if bom else spec.encoding.replace("utf-8-sig", "utf-8")
    return io.TextIOWrapper(b, encoding=enc, errors="replace", newline=""), bom


# ---------------------------------------------------------------------------- metadata


@dataclass
class FileMeta:
    hospital_name: str = ""
    last_updated_on_raw: str = ""
    last_updated_on: date | None = None
    version: str = ""
    location_names: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    license_number: str = ""
    license_state: str = ""
    type_2_npis: list[str] = field(default_factory=list)
    attestation: str = ""
    attester_name: str = ""
    other: dict[str, str] = field(default_factory=dict)
    had_bom: bool = False

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["last_updated_on"] = self.last_updated_on.isoformat() if self.last_updated_on else None
        return d


def _meta_from_pairs(pairs: list[tuple[str, str]], bom: bool) -> FileMeta:
    m = FileMeta(had_bom=bom)
    for k, v in pairs:
        key = k.strip().strip('"').lower()
        v = (v or "").strip()
        if not key and not v:
            continue
        if key == "hospital_name":
            m.hospital_name = v
        elif key == "last_updated_on":
            m.last_updated_on_raw = v
            m.last_updated_on = parse_date(v) if v else None
        elif key == "version":
            m.version = v
        elif key == "location_name":
            m.location_names = _dedup(v.split("|"))
        elif key == "hospital_address":
            m.addresses = _dedup(v.split("|"))
        elif key == "license_information.license_number":
            m.license_number = v
        elif key.startswith("license_number"):
            m.license_number = v
            m.license_state = key.split("|")[1].upper() if "|" in key else m.license_state
        elif key == "license_information.state":
            m.license_state = v
        elif key == "type_2_npi":
            m.type_2_npis = _dedup(v.split("|"))
        elif (
            key.startswith("to the best of its knowledge")
            or key == "attestation.confirm_attestation"
        ):
            m.attestation = v
        elif key == "attester_name" or key == "attestation.attester_name":
            m.attester_name = v
        elif key == "attestation.attestation":
            continue
        else:
            m.other[key[:80]] = v[:500]
    return m


def _csv_meta(reader: Iterator[list[str]], bom: bool) -> FileMeta:
    keys = _next(reader, "metadata header")
    vals = _next(reader, "metadata value")
    return _meta_from_pairs(list(zip(keys, vals + [""] * (len(keys) - len(vals)))), bom)


def _json_scan(spec: SourceSpec, path: Path) -> tuple[FileMeta, int, int, int]:
    """One ijson event pass: file metadata + the independent leaf / item / modifier counts."""
    b, bom = _open_binary(spec, path)
    pairs: list[tuple[str, str]] = []
    lists: dict[str, list[str]] = {}
    leaves = items = mods = 0
    charges_in_item = payers_in_charge = 0
    with b:
        for prefix, event, value in ijson.parse(b):
            if prefix.startswith("standard_charge_information"):
                if event == "start_map":
                    if prefix == _SCI:
                        items += 1
                        charges_in_item = 0
                    elif prefix == _CHG:
                        charges_in_item += 1
                        payers_in_charge = 0
                    elif prefix == _PAY:
                        payers_in_charge += 1
                elif event == "end_map":
                    if prefix == _CHG:
                        leaves += max(1, payers_in_charge)
                    elif prefix == _SCI and charges_in_item == 0:
                        leaves += 1
                continue
            if prefix.startswith("modifier_information"):
                if prefix == "modifier_information.item" and event == "start_map":
                    mods += 1
                continue
            if event in ("string", "number", "boolean"):
                if prefix.endswith(".item"):
                    lists.setdefault(prefix[: -len(".item")], []).append(_text(value))
                else:
                    pairs.append((prefix, _text(value)))
    for k, vs in lists.items():
        pairs.append((k, "|".join(vs)))
    return _meta_from_pairs(pairs, bom), leaves, items, mods


def read_meta(spec: SourceSpec, path: Path) -> FileMeta:
    if spec.format == "cms_v3_json":
        return _json_scan(spec, path)[0]
    fh, bom = _text_stream(spec, path)
    with fh:
        return _csv_meta(csv.reader(fh), bom)


# ---------------------------------------------------------------------------- independent counter


def count_leaves(spec: SourceSpec, path: Path) -> int:
    """Leaf count computed without the staging code path (used for row conservation)."""
    if spec.format == "cms_v3_json":
        return _json_scan(spec, path)[1]
    fh, _ = _text_stream(spec, path)
    with fh:
        r = csv.reader(fh)
        _next(r, "metadata header")
        _next(r, "metadata value")
        header = [h.strip().lower() for h in _next(r, "column header")]
        if spec.format == "cms_v3_csv_tall":
            return sum(1 for row in r if any(c.strip() for c in row))
        group_cols: dict[str, list[int]] = {}
        for i, h in enumerate(header):
            parts = h.split("|")
            if parts[0] == "standard_charge" and len(parts) == 4:
                group_cols.setdefault(parts[1].strip() + "|" + parts[2].strip(), []).append(i)
            elif parts[0] in WIDE_PREFIX_FIELDS and len(parts) == 3:
                group_cols.setdefault(parts[1].strip() + "|" + parts[2].strip(), []).append(i)
        n = 0
        for row in r:
            if not any(c.strip() for c in row):
                continue
            g = sum(
                1
                for cols in group_cols.values()
                if any(i < len(row) and row[i].strip() for i in cols)
            )
            n += max(1, g)
        return n


# ---------------------------------------------------------------------------- leaf readers


def _codes_from_csv(
    row: list[str], code_cols: list[tuple[int, int | None]]
) -> list[dict[str, str]]:
    out = []
    for ci, ti in code_cols:
        v = row[ci].strip() if ci < len(row) else ""
        if v:
            t = row[ti].strip().upper() if ti is not None and ti < len(row) else ""
            out.append({"code": v, "type": t})
    return out


def _blank() -> dict[str, Any]:
    return {f: "" for f in VALUE_FIELDS}


@dataclass
class _ReadStats:
    items: int = 0
    blank_rows: int = 0
    wide_payer_groups: int = 0
    modifier_items: int = 0
    header: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)


def _iter_csv(spec: SourceSpec, path: Path, st: _ReadStats) -> Iterator[tuple[int, list, dict]]:
    fh, _ = _text_stream(spec, path)
    with fh:
        r = csv.reader(fh)
        _next(r, "metadata header")
        _next(r, "metadata value")
        raw_header = _next(r, "column header")
        header = [h.strip() for h in raw_header]
        st.header = header
        hl = [h.lower() for h in header]
        code_cols: list[tuple[int, int | None]] = []
        n = 1
        while f"code|{n}" in hl:
            ti = hl.index(f"code|{n}|type") if f"code|{n}|type" in hl else None
            code_cols.append((hl.index(f"code|{n}"), ti))
            n += 1
        used = {ci for ci, _ in code_cols} | {ti for _, ti in code_cols if ti is not None}
        base: list[tuple[int, str]] = []
        groups: dict[tuple[str, str], list[tuple[int, str]]] = {}
        extra: list[tuple[int, str]] = []
        for i, h in enumerate(hl):
            if i in used:
                continue
            if h in CSV_MAP and (
                spec.format == "cms_v3_csv_tall" or CSV_MAP[h] not in _GROUP_FIELDS
            ):
                base.append((i, CSV_MAP[h]))
                continue
            parts = header[i].split("|")
            low = [p.lower() for p in parts]
            if spec.format == "cms_v3_csv_wide":
                if low[0] == "standard_charge" and len(parts) == 4 and low[3] in WIDE_SC_FIELDS:
                    groups.setdefault((parts[1].strip(), parts[2].strip()), []).append(
                        (i, WIDE_SC_FIELDS[low[3]])
                    )
                    continue
                if low[0] in WIDE_PREFIX_FIELDS and len(parts) == 3:
                    groups.setdefault((parts[1].strip(), parts[2].strip()), []).append(
                        (i, WIDE_PREFIX_FIELDS[low[0]])
                    )
                    continue
            if h:
                extra.append((i, header[i]))
        st.wide_payer_groups = len(groups)
        st.extra_columns = [h for _, h in extra]
        last: list[str] | None = None
        for row in r:
            if not any(c.strip() for c in row):
                st.blank_rows += 1
                continue
            last = row
            item = st.items
            st.items += 1
            codes = _codes_from_csv(row, code_cols)
            rec = _blank()
            for i, f in base:
                if i < len(row):
                    rec[f] = row[i]
            ex = {h: row[i] for i, h in extra if i < len(row) and row[i] != ""}
            rec["extra"] = json.dumps(ex, sort_keys=True) if ex else ""
            if spec.format == "cms_v3_csv_tall":
                yield item, codes, rec
                continue
            emitted = False
            for (payer, plan), cols in groups.items():
                vals = {f: row[i] for i, f in cols if i < len(row)}
                if not any(v.strip() for v in vals.values()):
                    continue
                emitted = True
                leaf = dict(rec)
                leaf.update(vals)
                leaf["payer_name"], leaf["plan_name"] = payer, plan
                yield item, codes, leaf
            if not emitted:
                yield item, codes, rec
        if last is not None and len(last) < len(header):  # truncated mid-row
            raise StageError(
                f"last data row has {len(last)} of {len(header)} columns: file truncated mid-row?"
            )


_GROUP_FIELDS = {
    "payer_name",
    "plan_name",
    "negotiated_dollar",
    "negotiated_percentage",
    "negotiated_algorithm",
    "estimated_amount",
    "median_amount",
    "p10",
    "p90",
    "count",
    "methodology",
    "additional_payer_notes",
}


def _iter_json(spec: SourceSpec, path: Path, st: _ReadStats) -> Iterator[tuple[int, list, dict]]:
    b, _ = _open_binary(spec, path)
    with b:
        for it in ijson.items(b, _SCI):
            item = st.items
            st.items += 1
            codes = [
                {"code": _text(c.get("code")).strip(), "type": _text(c.get("type")).strip().upper()}
                for c in it.get("code_information") or []
                if _text(c.get("code")).strip()
            ]
            base = _blank()
            base["description"] = _text(it.get("description"))
            di = it.get("drug_information") or {}
            base["drug_unit"] = _text(di.get("unit"))
            base["drug_type"] = _text(di.get("type"))
            item_extra = {f"item.{k}": v for k, v in it.items() if k not in JSON_ITEM_KEYS}
            charges = it.get("standard_charges") or []
            if not charges:
                rec = dict(base)
                rec["extra"] = (
                    json.dumps(item_extra, default=_text, sort_keys=True) if item_extra else ""
                )
                yield item, codes, rec
                continue
            for ch in charges:
                crec = dict(base)
                cextra = dict(item_extra)
                for k, v in ch.items():
                    if k == "payers_information":
                        continue
                    if k in JSON_CHARGE_MAP:
                        crec[JSON_CHARGE_MAP[k]] = _text(v)
                    else:
                        cextra[f"charge.{k}"] = v
                if not crec["modifiers"] and "charge.modifiers" in cextra:  # DFCI non-standard key
                    crec["modifiers"] = _text(cextra["charge.modifiers"])
                payers = ch.get("payers_information") or []
                if not payers:
                    crec["extra"] = (
                        json.dumps(cextra, default=_text, sort_keys=True) if cextra else ""
                    )
                    yield item, codes, crec
                    continue
                for p in payers:
                    rec = dict(crec)
                    pextra = dict(cextra)
                    for k, v in p.items():
                        if k in JSON_PAYER_MAP:
                            rec[JSON_PAYER_MAP[k]] = _text(v)
                        else:
                            pextra[f"payer.{k}"] = v
                    rec["extra"] = (
                        json.dumps(pextra, default=_text, sort_keys=True) if pextra else ""
                    )
                    yield item, codes, rec


def iter_leaves(
    spec: SourceSpec, path: Path, st: _ReadStats | None = None
) -> Iterator[tuple[int, list, dict]]:
    st = st or _ReadStats()
    if spec.format == "cms_v3_json":
        return _iter_json(spec, path, st)
    return _iter_csv(spec, path, st)


# ---------------------------------------------------------------------------- stage


@dataclass
class StageResult:
    source_id: str
    source_sha256: str
    raw_file: str
    staged_rows: int
    independent_count: int
    items: int
    blank_rows: int
    wide_payer_groups: int
    modifier_items: int
    extra_columns: list[str]
    meta: FileMeta
    seconds: float

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["meta"] = self.meta.to_json()
        return d


def stage_file(spec: SourceSpec, raw: Path, sha256: str, out: Path) -> StageResult:
    t0 = time.time()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.partial")
    try:
        return _stage(spec, raw, sha256, out, tmp, t0)
    except StageError:
        tmp.unlink(missing_ok=True)
        raise
    except (ijson.JSONError, csv.Error, zipfile.BadZipFile, UnicodeError, EOFError) as e:
        tmp.unlink(missing_ok=True)  # truncated / corrupt payload: one source fails, not the run
        raise StageError(f"{spec.source_id}: unreadable file ({type(e).__name__}: {e})") from e


def _stage(
    spec: SourceSpec, raw: Path, sha256: str, out: Path, tmp: Path, t0: float
) -> StageResult:
    if spec.format == "cms_v3_json":
        meta, expected, _, mods = _json_scan(spec, raw)
    else:
        meta, expected, mods = read_meta(spec, raw), count_leaves(spec, raw), 0
    st = _ReadStats(modifier_items=mods)
    n = 0
    batch: list[dict[str, Any]] = []
    writer = pq.ParquetWriter(tmp, SCHEMA, compression="zstd")
    try:
        for item, codes, rec in iter_leaves(spec, raw, st):
            rec["source_id"] = spec.source_id
            rec["source_sha256"] = sha256
            rec["stage_row"] = n
            rec["item_ordinal"] = item
            rec["codes"] = codes
            rec["code_values"] = "|" + "|".join(c["code"] for c in codes) + "|"
            batch.append(rec)
            n += 1
            if len(batch) >= BATCH:
                writer.write_table(pa.Table.from_pylist(batch, SCHEMA))
                batch.clear()
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, SCHEMA))
    finally:
        writer.close()
    if n != expected:
        tmp.unlink(missing_ok=True)
        raise StageError(
            f"{spec.source_id}: row conservation failed: staged {n} leaves, independent count {expected}"
        )
    tmp.replace(out)
    res = StageResult(
        source_id=spec.source_id,
        source_sha256=sha256,
        raw_file=raw.name,
        staged_rows=n,
        independent_count=expected,
        items=st.items,
        blank_rows=st.blank_rows,
        wide_payer_groups=st.wide_payer_groups,
        modifier_items=st.modifier_items,
        extra_columns=st.extra_columns,
        meta=meta,
        seconds=round(time.time() - t0, 2),
    )
    out.with_suffix(".meta.json").write_text(json.dumps(res.to_json(), indent=1, default=str))
    return res
