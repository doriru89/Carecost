"""TiC staging: target in_network items + every provider group -> lossless Parquet.

* ``prices.parquet``  one row per ``negotiated_prices[]`` entry of a target item (a rate group
  or item with no prices still gets one row with ``price_ordinal = -1``). All values are the
  source text; unknown keys go to ``extra`` (JSON).
* ``items.parquet``   one row per target item (header fields + item-level ``extra`` such as
  ``bundled_codes`` / ``covered_services``).
* ``groups.parquet``  one row per provider group in ``provider_references`` (every TIN + NPI
  list; no geographic filter here) and per inline ``provider_groups`` of a rate group.

Row conservation (else :class:`TicStageError`, nothing written): parsed prices == the count of
``"negotiated_rate":`` in the target items' bytes; groups with a TIN == the count of ``"tin":``
in the provider_references bytes.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.etl.npi import clean_npis
from app.etl.npi import count as count_npis
from app.etl.tic.scan import ScanResult, TargetItem

ITEM_KEYS = {
    "negotiation_arrangement", "name", "billing_code_type", "billing_code_type_version",
    "billing_code", "description", "negotiated_rates",
}  # fmt: skip
RG_KEYS = {"provider_references", "provider_groups", "negotiated_prices"}
PRICE_KEYS = {
    "negotiated_type", "negotiated_rate", "expiration_date", "service_code", "billing_class",
    "setting", "billing_code_modifier", "additional_information",
}  # fmt: skip
REF_KEYS = {"provider_group_id", "network_name", "provider_groups", "location"}
GROUP_KEYS = {"npi", "tin"}
TIN_KEYS = {"type", "value", "business_name"}

S = pa.string()
PRICE_SCHEMA = pa.schema(
    [
        ("source_id", S), ("source_sha256", S), ("stage_row", pa.int64()),
        ("item_ordinal", pa.int64()), ("billing_code_type", S), ("billing_code", S),
        ("rate_group_ordinal", pa.int64()), ("provider_references", pa.list_(pa.int64())),
        ("price_ordinal", pa.int64()), ("negotiated_type", S), ("negotiated_rate", S),
        ("expiration_date", S), ("setting", S), ("billing_class", S),
        ("service_code", pa.list_(S)), ("billing_code_modifier", pa.list_(S)),
        ("additional_information", S), ("extra", S),
    ]
)  # fmt: skip
ITEMS_SCHEMA = pa.schema(
    [
        ("source_id", S), ("source_sha256", S), ("item_ordinal", pa.int64()),
        ("raw_start", pa.int64()), ("raw_end", pa.int64()), ("billing_code_type", S),
        ("billing_code_type_version", S), ("billing_code", S), ("name", S), ("description", S),
        ("negotiation_arrangement", S), ("rate_groups", pa.int64()), ("prices", pa.int64()),
        ("independent_prices", pa.int64()), ("extra", S),
    ]
)  # fmt: skip
GROUP_SCHEMA = pa.schema(
    [
        ("source_id", S), ("source_sha256", S), ("provider_group_id", pa.int64()),
        ("group_ordinal", pa.int64()), ("network_name", pa.list_(S)), ("tin_type", S),
        ("tin_value", S), ("tin_digits", S), ("business_name", S), ("npis", pa.list_(S)),
        ("n_npi", pa.int64()), ("location", S), ("inline", pa.bool_()), ("extra", S),
    ]
)  # fmt: skip

BATCH = 50_000


class TicStageError(RuntimeError):
    pass


def _t(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True)
    return str(v)


def _extra(obj: dict[str, Any], known: set[str]) -> str:
    ex = {k: v for k, v in obj.items() if k not in known}
    return json.dumps(ex, sort_keys=True) if ex else ""


def _strs(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        v = [v]
    return [str(x) for x in v]


def digits(v: Any) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def inline_ref_id(item_ordinal: int, rg_ordinal: int) -> int:
    """Synthetic (negative) provider_group_id for groups written inline in a rate group."""
    return -(item_ordinal * 1_000_000 + rg_ordinal + 1)


def _group_rows(
    ref_id: int,
    ref: dict[str, Any],
    sid: str,
    sha: str,
    inline: bool,
    dropped_npis: Counter[str] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    groups = ref.get("provider_groups")
    nn = _strs(ref.get("network_name"))
    ref_extra = _extra(ref, REF_KEYS) if not inline else ""
    if not groups:
        rows.append(
            dict(
                source_id=sid, source_sha256=sha, provider_group_id=ref_id, group_ordinal=-1,
                network_name=nn, tin_type="", tin_value="", tin_digits="", business_name="",
                npis=[], n_npi=0, location=_t(ref.get("location")), inline=inline, extra=ref_extra,
            )
        )  # fmt: skip
        return rows
    for gi, g in enumerate(groups):
        tin = g.get("tin") or {}
        npis, bad = clean_npis(_strs(g.get("npi")))  # R10: placeholders ("0") never staged as NPIs
        ex: dict[str, Any] = {}
        if bad:
            ex["dropped_npis"] = bad
            if dropped_npis is not None:
                dropped_npis.update(count_npis(bad))
        if g.keys() - GROUP_KEYS:
            ex["group"] = {k: v for k, v in g.items() if k not in GROUP_KEYS}
        if isinstance(tin, dict) and tin.keys() - TIN_KEYS:
            ex["tin"] = {k: v for k, v in tin.items() if k not in TIN_KEYS}
        if ref_extra and gi == 0:
            ex["ref"] = json.loads(ref_extra)
        rows.append(
            dict(
                source_id=sid, source_sha256=sha, provider_group_id=ref_id, group_ordinal=gi,
                network_name=nn, tin_type=_t(tin.get("type")) if isinstance(tin, dict) else "",
                tin_value=_t(tin.get("value")) if isinstance(tin, dict) else _t(tin),
                tin_digits=digits(tin.get("value") if isinstance(tin, dict) else tin),
                business_name=_t(tin.get("business_name")) if isinstance(tin, dict) else "",
                npis=npis, n_npi=len(npis), location="", inline=inline,
                extra=json.dumps(ex, sort_keys=True) if ex else "",
            )
        )  # fmt: skip
    return rows


class _Writer:
    def __init__(self, path: Path, schema: pa.Schema) -> None:
        self.path = path
        self.tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.w = pq.ParquetWriter(self.tmp, schema, compression="zstd")
        self.schema = schema
        self.buf: list[dict[str, Any]] = []
        self.rows = 0

    def add(self, row: dict[str, Any]) -> None:
        self.buf.append(row)
        if len(self.buf) >= BATCH:
            self.flush()

    def flush(self) -> None:
        if self.buf:
            self.w.write_table(pa.Table.from_pylist(self.buf, self.schema))
            self.rows += len(self.buf)
            self.buf = []

    def commit(self) -> None:
        self.flush()
        self.w.close()
        os.replace(self.tmp, self.path)

    def abort(self) -> None:
        try:
            self.w.close()
        finally:
            self.tmp.unlink(missing_ok=True)


@dataclass
class StageStats:
    source_id: str
    source_sha256: str
    target_items: int = 0
    price_rows: int = 0
    prices_parsed: int = 0
    independent_prices: int = 0
    empty_rate_groups: int = 0
    group_rows: int = 0
    groups_with_tin: int = 0
    independent_groups: int = 0
    inline_group_rows: int = 0
    remote_refs: int = 0
    provider_references: int = 0
    codes: dict[str, int] = field(default_factory=dict)
    npi_placeholders_dropped: dict[str, int] = field(default_factory=dict)  # R10, per value


class Stager:
    """Feed it the scan stream (target items, then the ScanResult)."""

    def __init__(self, out_dir: Path, source_id: str, sha: str, stage_row_start: int = 0) -> None:
        """``stage_row_start``: ``tic extend`` numbers new rows after the existing ones, so every
        row reference already cited keeps pointing at the same row."""
        self.sid, self.sha = source_id, sha
        self.out_dir = out_dir
        self.prices = _Writer(out_dir / "prices.parquet", PRICE_SCHEMA)
        self.items = _Writer(out_dir / "items.parquet", ITEMS_SCHEMA)
        self.inline: list[dict[str, Any]] = []
        self.stats = StageStats(source_id, sha)
        self.stage_row = self.stage_row_start = stage_row_start
        self.dropped_npis: Counter[str] = Counter()

    def add_item(self, t: TargetItem) -> None:
        o, st = t.obj, self.stats
        st.target_items += 1
        st.codes[o.get("billing_code", "")] = st.codes.get(o.get("billing_code", ""), 0) + 1
        n_prices = 0
        rgs = o.get("negotiated_rates") or []
        base = dict(
            source_id=self.sid, source_sha256=self.sha, item_ordinal=t.ref.ordinal,
            billing_code_type=_t(o.get("billing_code_type")), billing_code=_t(o.get("billing_code")),
        )  # fmt: skip
        for gi, rg in enumerate(rgs if rgs else [{}]):
            refs = [int(x) for x in rg.get("provider_references") or []]
            if rg.get("provider_groups"):
                rid = inline_ref_id(t.ref.ordinal, gi)
                refs.append(rid)
                self.inline += _group_rows(
                    rid, rg, self.sid, self.sha, inline=True, dropped_npis=self.dropped_npis
                )
            rg_extra = _extra(rg, RG_KEYS)
            prices = rg.get("negotiated_prices") or []
            if not prices:
                st.empty_rate_groups += 1
            for pi, p in enumerate(prices if prices else [None]):
                p = p or {}
                ex = {}
                if rg_extra:
                    ex["rate_group"] = json.loads(rg_extra)
                if p.keys() - PRICE_KEYS:
                    ex["price"] = {k: v for k, v in p.items() if k not in PRICE_KEYS}
                self.prices.add(
                    dict(
                        base, stage_row=self.stage_row, rate_group_ordinal=gi if rgs else -1,
                        provider_references=refs, price_ordinal=pi if prices else -1,
                        negotiated_type=_t(p.get("negotiated_type")),
                        negotiated_rate=_t(p.get("negotiated_rate")),
                        expiration_date=_t(p.get("expiration_date")), setting=_t(p.get("setting")),
                        billing_class=_t(p.get("billing_class")),
                        service_code=_strs(p.get("service_code")),
                        billing_code_modifier=_strs(p.get("billing_code_modifier")),
                        additional_information=_t(p.get("additional_information")),
                        extra=json.dumps(ex, sort_keys=True) if ex else "",
                    )
                )  # fmt: skip
                self.stage_row += 1
                if prices:
                    n_prices += 1
        st.prices_parsed += n_prices
        st.independent_prices += t.independent_prices
        self.items.add(
            dict(
                source_id=self.sid, source_sha256=self.sha, item_ordinal=t.ref.ordinal,
                raw_start=t.ref.raw_start, raw_end=t.ref.raw_end,
                billing_code_type=_t(o.get("billing_code_type")),
                billing_code_type_version=_t(o.get("billing_code_type_version")),
                billing_code=_t(o.get("billing_code")), name=_t(o.get("name")),
                description=_t(o.get("description")),
                negotiation_arrangement=_t(o.get("negotiation_arrangement")),
                rate_groups=len(rgs), prices=n_prices, independent_prices=t.independent_prices,
                extra=_extra(o, ITEM_KEYS),
            )
        )  # fmt: skip

    def finish(self, res: ScanResult) -> StageStats:
        st = self.stats
        groups = _Writer(self.out_dir / "groups.parquet", GROUP_SCHEMA)
        try:
            for ref in res.provider_references:
                rid = int(ref.get("provider_group_id", -0))
                rows = _group_rows(
                    rid, ref, self.sid, self.sha, inline=False, dropped_npis=self.dropped_npis
                )
                st.remote_refs += int(bool(ref.get("location")) and not ref.get("provider_groups"))
                for r in rows:
                    groups.add(r)
                    st.group_rows += 1
                    st.groups_with_tin += int(bool(r["tin_value"]) or r["group_ordinal"] >= 0)
            for r in self.inline:
                groups.add(r)
                st.group_rows += 1
                st.inline_group_rows += 1
            st.provider_references = len(res.provider_references)
            st.independent_groups = res.independent_groups
            st.price_rows = self.stage_row - self.stage_row_start
            st.npi_placeholders_dropped = dict(sorted(self.dropped_npis.items()))
            if st.prices_parsed != st.independent_prices:
                raise TicStageError(
                    f"{self.sid}: prices parsed {st.prices_parsed} != independent count "
                    f"{st.independent_prices}"
                )
            if st.groups_with_tin != st.independent_groups:
                raise TicStageError(
                    f"{self.sid}: provider groups {st.groups_with_tin} != independent "
                    f"'\"tin\":' count {st.independent_groups}"
                )
        except BaseException:
            groups.abort()
            self.abort()
            raise
        groups.commit()
        self.prices.commit()
        self.items.commit()
        return st

    def abort(self) -> None:
        self.prices.abort()
        self.items.abort()


def stats_json(st: StageStats) -> str:
    return json.dumps(asdict(st), indent=1, sort_keys=True)


def read_groups(path: Path) -> dict[int, list[dict[str, Any]]]:
    cols = ["provider_group_id", "group_ordinal", "tin_type", "tin_value", "tin_digits",
            "business_name", "n_npi", "location"]  # fmt: skip
    out: dict[int, list[dict[str, Any]]] = {}
    for r in pq.read_table(path, columns=cols).to_pylist():
        out.setdefault(r["provider_group_id"], []).append(r)
    return out
