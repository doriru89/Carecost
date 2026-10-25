"""Rate rows for the quote engine: one runtime file, loaded once at startup into in-memory dicts.

Runtime format (P1 problem 11): **one SQLite file, the quote pack** (``quote_pack.sqlite``). The
server reads it with the stdlib ``sqlite3`` module, so the image needs no pyarrow. The pack is
written by ``python -m app.quote.pack`` (ETL side, where pyarrow is available) from

* a hospital ETL build (``rate_row.sqlite`` + ``manifest.json``),
* the insurer TiC intermediates (``<tic_root>/<source_id>/CURRENT`` -> ``rate_row.parquet``,
  ``groups.parquet``, ``run.json``),
* government fee-schedule rate rows (Medicare PFS / OPPS / ASC, MassHealth) in the RateRow
  contract plus their freshness inputs,

or from the small committed extract (``contracts/fixtures/rate_row_extract.csv`` +
``rate_row_extract.sources.yaml``), so tests and CI read the same format without the 1 GB of data.

Why SQLite and not JSON / parquet: one stdlib reader for every source kind, a few hundred MB
of rows stream in without a JSON parse of the whole file, and ``sqlite3`` can filter rows at load
time (only the codes we price, only the TINs the site registry links). Rows are still copied into
dicts at startup (P1 design, metrics F1): no query runs per request.

Indexes (what a quote looks up):

* ``by_code[(source_id, code)]``: hospital MRF and fee-schedule rows for one code;
* ``hospital[(source_id, code, payer_id)]``: a hospital file's rows for one code and payer
  (``""`` for chargemaster rows and unmapped payers);
* ``cash[(source_id, code)]``: rows with a discounted cash price, one per distinct
  (modifiers, component, setting, cash, gross), keeping the lowest stage_row (tall CSVs repeat
  the hospital-wide cash price on every payer row);
* ``tic[(source_id, tin, code)]``: TiC rows for one billing TIN (9 digits, or a 10-digit NPI when
  the TiC file keys the contract by NPI) and code;
* ``npi_sets[id]``: the NPIs behind one packed TiC row (D6 per-doctor prices; only when every
  provider group folded into the row lists at most ``MAX_GROUP_NPIS`` NPIs);
* ``census_tins[census_id]``: billing TINs the TiC matcher linked to a clinic-census site
  (``tic_site_ids``) that the site registry does not list in ``Site.tins``. Rows of such a TIN
  count for that site only when they name the site (``Row.site_ids``).

TiC rows are **aggregated at pack time** (C2, memory): rows of one network file that agree on
billing TIN x code x modifier x place-of-service list x amount x percent x billing class x
negotiated type x group name x linked sites are one packed row. The packed row keeps the identity
(row_id, row_ref, stage_row) of the lowest staged row of the bunch, so its number still cites a real
row with exactly that number, and the union of the bunch's NPIs.

``Recorder`` collects every row a lookup returned, so the fixture generator can write an extract
that reproduces the same quotes exactly.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.etl.contracts import FEE_SCHEDULE_KINDS as _FS_KINDS
from app.etl.contracts import (
    Method,
    PriceBasis,
    Provenance,
    SourceKind,
    fee_schedule_method,
    number_payer,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXTRACT_CSV = REPO_ROOT / "contracts" / "fixtures" / "rate_row_extract.csv"
EXTRACT_SOURCES = REPO_ROOT / "contracts" / "fixtures" / "rate_row_extract.sources.yaml"
PACK_VERSION = 3

FEE_SCHEDULE_KINDS = frozenset(k.value for k in _FS_KINDS)
PACKED_MODIFIERS = frozenset({"", "26", "TC"})
"""Modifiers the engine prices with: none, professional component (26), technical component (TC).
Every other modifier (52 reduced, 55 post-op only, 78 return to OR, 50 bilateral ...) describes a
different service, so its rows are left out of the pack."""

MAX_GROUP_NPIS = 25
"""D6: NPIs are packed only for TiC provider groups this small; a by-doctor list longer than this
is not useful on a receipt (the line shows the group range instead)."""


@dataclass(frozen=True, slots=True)
class Row:
    """The rate_row columns the quote engine reads (hospital MRF, TiC and fee-schedule rows)."""

    source_id: str
    source_kind: str
    row_id: str  # unique per build; row_ref is NOT unique (one TiC price row serves many groups)
    ref: str  # row_ref, or "" when it is the standard <source_id>:<sha12>:<stage_row>
    stage_row: int
    row_kind: str
    code: str
    modifiers: str
    component: str
    billing_class: str
    setting: str
    rev_code: str
    payer_id: str | None
    product: str
    line_of_business: str
    plan_raw: str
    amount: float | None
    amount_method: str
    negotiated_pct: float | None
    discounted_cash: float | None
    gross: float | None
    entity_id: str = ""  # fee schedules: price area (medicare_ma_01, medicare_national, masshealth)
    place_of_service: str = ""  # fee schedules: non_facility | facility | "" (not split)
    tin: str = ""  # TiC billing TIN (digits only) or NPI
    tin_type: str = ""  # TiC: ein | npi
    service_codes: str = ""  # TiC place-of-service codes, '|'-joined
    business_name: str = ""
    negotiated_type: str = ""  # TiC: negotiated | fee schedule | percentage | ...
    site_ids: str = ""  # TiC: ';'-joined census ids the matcher linked the group to
    npi_set: int = 0  # TiC: id into RateStore.npi_sets (0 = NPIs unknown or too many)

    @property
    def uid(self) -> str:
        return f"{self.source_id}:{self.row_id}"

    def pos(self) -> frozenset[str]:
        return frozenset(self.service_codes.split("|")) if self.service_codes else frozenset()

    def names_site(self, census_id: str) -> bool:
        return census_id in self.site_ids.split(";") if self.site_ids else False


ROW_COLUMNS = [f.name for f in fields(Row)]


@dataclass(frozen=True)
class SourceMeta:
    """One source, stored once (P2): what its chip says and its freshness inputs (D18)."""

    source_id: str
    source_kind: str
    publisher: str
    source_file: str
    source_sha256: str
    source_date: str | None  # the file's own date (ISO) printed in Provenance.source_date
    last_updated: str | None  # (a) publisher's own date (ISO)
    fetched_at: str  # (b) our last successful fetch (ISO date)
    source_rule: str
    our_rule: str
    expected_by: str | None = None  # release-based rules only (fee schedules)
    our_refresh_due: str | None = None
    payer_id: str | None = None  # TiC: whose network file
    product: str = ""  # TiC: HMO / PPO / ...
    network_label: str = ""  # TiC: "HMO Blue (fully insured)"
    line_of_business: str = ""  # TiC: commercial / connector

    def row_ref(self, row: Row) -> str:
        return row.ref or f"{self.source_id}:{self.source_sha256[:12]}:{row.stage_row}"


SOURCE_COLUMNS = [f.name for f in fields(SourceMeta)]

DEFAULT_RULES = {
    "hospital_mrf": ("hospital_mrf_365_days", "hospital_monthly"),
    "insurer_tic": ("tic_45_days", "tic_monthly"),
    "clinic_posted": ("posted_page_date_365_days", "sites_weekly"),
}


@dataclass
class DataVersionInfo:
    build_id: str
    build_date: str
    tic_release: str | None


@dataclass
class Recorder:
    refs: set[str] = field(default_factory=set)

    def add(self, rows: Iterable[Row]) -> None:
        self.refs.update(r.uid for r in rows)


@dataclass
class RateStore:
    rows: list[Row]
    sources: dict[str, SourceMeta]
    version: DataVersionInfo
    codes: frozenset[str] = frozenset()  # codes the hospital / TiC ETL loads (codes.yaml)
    npi_sets: dict[int, tuple[str, ...]] = field(default_factory=dict)
    census_tins: dict[str, frozenset[str]] = field(default_factory=dict)
    refresh_status: dict[str, dict[str, Any]] = field(default_factory=dict)  # P11 (ETL side)
    by_code: dict[tuple[str, str], list[Row]] = field(default_factory=dict)
    hospital: dict[tuple[str, str, str], list[Row]] = field(default_factory=dict)
    cash: dict[tuple[str, str], list[Row]] = field(default_factory=dict)
    tic: dict[tuple[str, str, str], list[Row]] = field(default_factory=dict)
    recorder: Recorder | None = None
    flags: dict[str, frozenset[str]] = field(default_factory=dict)
    """C4b item 4: A6's TiC row flags (``flags.parquet``, joined on row_id at pack time) by
    ``Row.uid``: same_npi_pos_multi_rate, anesthesia_per_unit, institutional_on_physician_npi."""

    def __post_init__(self) -> None:
        self._index()

    def _index(self) -> None:
        by_code: dict[tuple[str, str], list[Row]] = defaultdict(list)
        hosp: dict[tuple[str, str, str], list[Row]] = defaultdict(list)
        cash_best: dict[tuple, Row] = {}
        tic: dict[tuple[str, str, str], list[Row]] = defaultdict(list)
        self.rows.sort(key=lambda r: (r.source_id, r.stage_row, r.row_id))
        for r in self.rows:
            if r.source_kind == "insurer_tic":
                tic[(r.source_id, r.tin, r.code)].append(r)
                continue
            by_code[(r.source_id, r.code)].append(r)
            if r.source_kind == "hospital_mrf":
                hosp[(r.source_id, r.code, r.payer_id or "")].append(r)
                if r.discounted_cash is not None:
                    k = (r.source_id, r.code, r.modifiers, r.component, r.setting,
                         r.discounted_cash, r.gross)  # fmt: skip
                    cash_best.setdefault(k, r)  # rows are sorted: first = lowest stage_row
        cash: dict[tuple[str, str], list[Row]] = defaultdict(list)
        for k, r in cash_best.items():
            cash[(k[0], k[1])].append(r)
        self.by_code, self.hospital = dict(by_code), dict(hosp)
        self.cash, self.tic = dict(cash), dict(tic)

    def get(self, index: str, key: tuple) -> list[Row]:
        rows = getattr(self, index).get(key, [])
        if self.recorder is not None:
            self.recorder.add(rows)
        return rows

    def row_flags(self, r: Row) -> frozenset[str]:
        return self.flags.get(r.uid, frozenset()) if self.flags else frozenset()

    def npis(self, r: Row) -> tuple[str, ...]:
        return self.npi_sets.get(r.npi_set, ()) if r.npi_set else ()

    def by_uid(self) -> dict[str, Row]:
        """uid -> Row (the fixture generator only; the server never builds it)."""
        return {r.uid: r for r in self.rows}

    def has_kind(self, kind: str) -> bool:
        return any(m.source_kind == kind for m in self.sources.values())

    def sources_of(self, kind: str) -> list[str]:
        return sorted(s for s, m in self.sources.items() if m.source_kind == kind)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for r in self.rows:
            out[r.source_id] += 1
        return dict(sorted(out.items()))

    # ------------------------------------------------------------------ provenance

    def prov_dict(self, r: Row, basis: PriceBasis, *, method: Method | None = None,
                  payer_id: str | None = None) -> dict[str, Any]:  # fmt: skip
        """``prov(...).model_dump(mode="json")`` without building the model (the quote validates
        the whole response once). ``payer_id`` overrides the number's payer (C3: a peer estimate
        built from one payer's rates keeps that payer)."""
        m = self.sources[r.source_id]
        if method is None:
            if r.source_kind in FEE_SCHEDULE_KINDS:
                method = fee_schedule_method(r.source_kind)
            elif r.amount_method == "derived_pct_x_gross" and basis == PriceBasis.negotiated:
                method = Method.derived_pct_x_gross
            else:
                method = Method.stated
        return {
            "source_id": r.source_id,
            "source_kind": r.source_kind,
            "source_file": m.source_file,
            "source_sha256": m.source_sha256,
            "source_date": m.source_date or None,
            "method": method.value,
            "row_ref": m.row_ref(r),
            "payer_id": payer_id
            if payer_id is not None
            else number_payer(r.row_kind, r.payer_id, basis),
            "row_id": r.row_id if r.source_kind == "insurer_tic" else None,
        }

    def prov(self, r: Row, basis: PriceBasis, *, method: Method | None = None) -> Provenance:
        m = self.sources[r.source_id]
        if method is None:
            if r.source_kind in FEE_SCHEDULE_KINDS:
                method = fee_schedule_method(r.source_kind)
            elif r.amount_method == "derived_pct_x_gross" and basis == PriceBasis.negotiated:
                method = Method.derived_pct_x_gross
            else:
                method = Method.stated
        return Provenance(
            source_id=r.source_id,
            source_kind=SourceKind(r.source_kind),
            source_file=m.source_file,
            source_sha256=m.source_sha256,
            source_date=date.fromisoformat(m.source_date) if m.source_date else None,
            method=method,
            row_ref=m.row_ref(r),
            payer_id=number_payer(r.row_kind, r.payer_id, basis),
            row_id=r.row_id if r.source_kind == "insurer_tic" else None,
        )


# --------------------------------------------------------------------------- converters


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    return float(v)


def _s(v: Any) -> str:
    return "" if v is None else str(v)


def _i(v: Any) -> int:
    return 0 if v is None or v == "" else int(v)


def tin_digits(v: Any) -> str:
    return "".join(ch for ch in _s(v) if ch.isdigit())


def valid_npi(n: str) -> bool:
    """A CMS NPI: 10 digits starting with 1 or 2. Insurer files use "0" (and other short values)
    as a placeholder for "no NPI"; a placeholder is "unknown", never an NPI (R10: one "0" in a
    Tufts file turned every quote near Milton into a 500)."""
    return len(n) == 10 and n.isdigit() and n[0] in "12"


_intern = sys.intern


def make_row(d: dict[str, Any]) -> Row:
    """A Row from a dict in ROW_COLUMNS (pack / extract) or RateRow columns (ETL outputs)."""
    sid = _s(d["source_id"])
    return Row(
        source_id=_intern(sid),
        source_kind=_intern(_s(d["source_kind"])),
        row_id=_s(d["row_id"]),
        ref=_s(d.get("ref", "")),
        stage_row=int(d["stage_row"]),
        row_kind=_intern(_s(d["row_kind"])),
        code=_intern(_s(d["code"])),
        modifiers=_intern(_s(d["modifiers"])),
        component=_intern(_s(d["component"])),
        billing_class=_intern(_s(d["billing_class"])),
        setting=_intern(_s(d["setting"])),
        rev_code=_intern(_s(d.get("rev_code"))),
        payer_id=_intern(d["payer_id"]) if d.get("payer_id") else None,
        product=_intern(_s(d.get("product"))),
        line_of_business=_intern(_s(d.get("line_of_business"))),
        plan_raw=_intern(_s(d.get("plan_raw"))),
        amount=_f(d.get("amount")),
        amount_method=_intern(_s(d.get("amount_method"))),
        negotiated_pct=_f(d.get("negotiated_pct")),
        discounted_cash=_f(d.get("discounted_cash")),
        gross=_f(d.get("gross")),
        entity_id=_intern(_s(d.get("entity_id"))),
        place_of_service=_intern(_s(d.get("place_of_service", legacy_pos(d)))),
        tin=_intern(tin_digits(d.get("tin", d.get("tic_tin_value")))),
        tin_type=_intern(_s(d.get("tin_type", d.get("tic_tin_type")))),
        service_codes=_intern(_s(d.get("service_codes", d.get("tic_service_codes")))),
        business_name=_intern(_s(d.get("business_name", d.get("tic_business_name")))),
        negotiated_type=_intern(_s(d.get("negotiated_type", d.get("tic_negotiated_type")))),
        site_ids=_intern(_s(d.get("site_ids", d.get("tic_site_ids")))),
        npi_set=_i(d.get("npi_set")),
    )


def legacy_pos(d: dict[str, Any]) -> str:
    """Fee-schedule rows written before RateRow.place_of_service existed carried it in plan_raw
    (A3's 2026-10-24 parquet). Hospital / TiC rows: ''."""
    if _s(d.get("source_kind")) in FEE_SCHEDULE_KINDS and d.get("plan_raw") in (
        "non_facility",
        "facility",
    ):
        return _s(d["plan_raw"])
    return ""


def standard_ref(meta: SourceMeta, row_ref: str, stage_row: int) -> str:
    """'' when ``row_ref`` is the standard form (saves one string per row in memory)."""
    return "" if row_ref == f"{meta.source_id}:{meta.source_sha256[:12]}:{stage_row}" else row_ref


# --------------------------------------------------------------------------- pack (runtime format)

STRING_COLUMNS = (
    "source_id", "source_kind", "row_kind", "code", "modifiers", "component", "billing_class",
    "setting", "rev_code", "payer_id", "product", "line_of_business", "plan_raw", "amount_method",
    "entity_id", "place_of_service", "tin", "tin_type", "service_codes", "business_name",
    "negotiated_type", "site_ids",
)  # fmt: skip
"""Low-cardinality text columns are stored as ids into ``strings`` (the pack is ~5x smaller and
loading resolves each id to one shared Python string)."""

_SCHEMA = f"""
create table meta (key text primary key, value text not null);
create table sources ({", ".join(f"{c} text" for c in SOURCE_COLUMNS)}, primary key (source_id));
create table strings (id integer primary key, s text not null);
create table rows ({", ".join(ROW_COLUMNS)});
create table npi_sets (id integer, npi text);
create table census_tins (census_id text, tin text);
create table row_flags (source_id text, row_id text, flags text);
"""


def _cell(v: Any) -> Any:
    if isinstance(v, bool):
        return 1 if v else 0
    return v


def write_pack(
    path: Path,
    *,
    rows: Iterable[Row],
    sources: dict[str, SourceMeta],
    version: DataVersionInfo,
    codes: Iterable[str],
    npi_sets: dict[int, tuple[str, ...]] | None = None,
    census_tins: dict[str, Iterable[str]] | None = None,
    refresh_status: dict[str, dict[str, Any]] | None = None,
    flags: dict[str, frozenset[str]] | None = None,
) -> int:
    """``npi_sets`` / ``census_tins`` may be filled while ``rows`` streams (they are written after
    the rows)."""
    """Write the runtime pack. Returns the number of rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(_SCHEMA)
    meta = {
        "pack_version": str(PACK_VERSION),
        "build_id": version.build_id,
        "build_date": version.build_date,
        "tic_release": version.tic_release or "",
        "codes": json.dumps(sorted(set(codes))),
        "refresh_status": json.dumps(refresh_status or {}, sort_keys=True),
    }
    db.executemany("insert into meta values (?, ?)", meta.items())
    db.executemany(
        f"insert into sources values ({','.join('?' * len(SOURCE_COLUMNS))})",
        [[getattr(m, c) for c in SOURCE_COLUMNS] for m in sources.values()],
    )
    n = 0
    q = f"insert into rows values ({','.join('?' * len(ROW_COLUMNS))})"
    ids: dict[str | None, int | None] = {None: None}
    coded = set(STRING_COLUMNS)

    def sid(v: str | None) -> int | None:
        if v not in ids:
            ids[v] = len(ids)
        return ids[v]

    batch: list[list[Any]] = []
    for r in rows:
        if r.source_id not in sources:
            raise ValueError(f"row {r.uid}: source {r.source_id} has no SourceMeta")
        batch.append([sid(getattr(r, c)) if c in coded else _cell(getattr(r, c))
                      for c in ROW_COLUMNS])  # fmt: skip
        n += 1
        if len(batch) >= 50_000:
            db.executemany(q, batch)
            batch.clear()
    db.executemany(q, batch)
    db.executemany("insert into strings values (?, ?)",
                   [(i, v) for v, i in ids.items() if v is not None])  # fmt: skip
    db.executemany(
        "insert into npi_sets values (?, ?)",
        [(i, npi) for i, npis in (npi_sets or {}).items() for npi in npis],
    )
    db.executemany(
        "insert into census_tins values (?, ?)",
        [(c, t) for c, tins in sorted((census_tins or {}).items()) for t in sorted(tins)],
    )
    db.executemany(
        "insert into row_flags values (?, ?, ?)",
        [
            (*uid.split(":", 1), "|".join(sorted(f)))
            for uid, f in sorted((flags or {}).items())
            if f
        ],
    )
    db.execute("create index rows_tin on rows (tin)")
    db.commit()
    db.close()
    os.replace(tmp, path)
    return n


def load_pack(
    path: Path, *, tins: Iterable[str] | None = None, census_ids: Iterable[str] = ()
) -> RateStore:
    """Load the pack into memory. ``tins``: keep only TiC rows of these billing TINs / NPIs (the
    site registry's) plus the TINs the TiC matcher linked to ``census_ids``, so a registry of 6
    sites does not hold 1.5 million TiC rows. None = all."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    meta = {k: v for k, v in db.execute("select key, value from meta")}
    if int(meta["pack_version"]) != PACK_VERSION:
        raise SystemExit(f"{path}: pack version {meta['pack_version']} != {PACK_VERSION}")
    sources = {
        rec["source_id"]: SourceMeta(**{c: rec[c] for c in SOURCE_COLUMNS})
        for rec in db.execute("select * from sources")
    }
    strings = {i: sys.intern(v) for i, v in db.execute("select id, s from strings")}
    coded = [c in STRING_COLUMNS for c in ROW_COLUMNS]
    sql = f"select {', '.join(ROW_COLUMNS)} from rows"
    args: list[Any] = []
    census: dict[str, set[str]] = defaultdict(set)
    for c, t in db.execute("select census_id, tin from census_tins"):
        census[c].add(t)
    if tins is not None:
        cids = set(census_ids)
        tins = set(tins) | {t for c in cids for t in census.get(c, ())}
        census = {c: v for c, v in census.items() if c in cids}
        inv = {v: k for k, v in strings.items()}
        tic = inv.get("insurer_tic", -1)
        want = sorted({inv[t] for t in tins if t in inv})
        db.execute("create temp table want (tin integer primary key)")
        db.executemany("insert into temp.want values (?)", [(t,) for t in want])
        sql += f" where source_kind != {tic} or tin in (select tin from temp.want)"
    db.row_factory = None
    rows: list[Row] = []
    ip = ROW_COLUMNS.index("payer_id")
    for rec in db.execute(sql, args):
        vals = [strings.get(v, "") if c and v is not None else v for c, v in zip(coded, rec)]
        if vals[ip] in ("", None):
            vals[ip] = None
        rows.append(Row(*vals))
    used = {r.npi_set for r in rows if r.npi_set}
    npis: dict[int, list[str]] = defaultdict(list)
    flags: dict[str, frozenset[str]] = {}
    has_flags = db.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'row_flags'"
    ).fetchone()
    if has_flags:  # packs built before C4b have no flags table
        for src, rid, fl in db.execute("select source_id, row_id, flags from row_flags"):
            flags[f"{src}:{rid}"] = frozenset(fl.split("|"))
    for i, npi in db.execute("select id, npi from npi_sets order by id, npi"):
        if i in used and valid_npi(npi):  # packs built before the pack-side filter carry "0"
            npis[i].append(sys.intern(npi))
    db.close()
    version = DataVersionInfo(
        build_id=meta["build_id"],
        build_date=meta["build_date"],
        tic_release=meta["tic_release"] or None,
    )
    return RateStore(
        rows=rows,
        sources=sources,
        version=version,
        codes=frozenset(json.loads(meta["codes"])),
        npi_sets={k: tuple(v) for k, v in npis.items()},
        census_tins={c: frozenset(v) for c, v in census.items()},
        refresh_status=json.loads(meta.get("refresh_status") or "{}"),
        flags=flags,
    )


# --------------------------------------------------------------------------- committed extract


def _csv_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


def write_extract(store: RateStore, uids: Iterable[str], csv_path: Path, sources_path: Path) -> int:
    """Write the rows in ``uids`` (CSV, one per line, diffable) and their sources (YAML)."""
    idx = store.by_uid()
    out = sorted({idx[u] for u in uids}, key=lambda r: (r.source_id, r.stage_row, r.row_id))
    used = {r.source_id for r in out}
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, ["row_ref", *ROW_COLUMNS, "npis", "flags"], lineterminator="\n")
        w.writeheader()
        for r in out:
            d = {c: _csv_value(getattr(r, c)) for c in ROW_COLUMNS}
            d["row_ref"] = store.sources[r.source_id].row_ref(r)
            d["ref"] = ""
            d["npi_set"] = ""
            d["npis"] = "|".join(store.npis(r))
            d["flags"] = "|".join(sorted(store.row_flags(r)))
            w.writerow(d)
    doc = {
        "version": 2,
        "note": "Freshness inputs for the sources in rate_row_extract.csv. Written by "
        "python -m app.quote.fixtures_gen; do not edit by hand.",
        "data_version": {
            "build_id": store.version.build_id,
            "build_date": store.version.build_date,
            "tic_release": store.version.tic_release,
        },
        "codes": sorted(store.codes),
        "census_tins": {
            c: sorted(t)
            for c, t in sorted(store.census_tins.items())
            if any(r.names_site(c) for r in out)
        },
        "sources": {
            sid: {k: v for k, v in m.__dict__.items() if k != "source_id"}
            for sid, m in sorted(store.sources.items())
            if sid in used
        },
    }
    sources_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return len(out)


def read_extract(
    csv_path: Path = EXTRACT_CSV, sources_path: Path = EXTRACT_SOURCES
) -> tuple[list[Row], dict[str, SourceMeta], DataVersionInfo, list[str], dict, dict, dict]:
    doc = yaml.safe_load(sources_path.read_text())
    sources = {sid: SourceMeta(source_id=sid, **m) for sid, m in doc["sources"].items()}
    rows: list[Row] = []
    npis: dict[int, tuple[str, ...]] = {}
    set_ids: dict[tuple[str, ...], int] = {}
    flags: dict[str, frozenset[str]] = {}
    with csv_path.open() as f:
        for d in csv.DictReader(f):
            if d.get("flags"):
                flags[f"{d['source_id']}:{d['row_id']}"] = frozenset(d["flags"].split("|"))
            meta = sources[d["source_id"]]
            d["ref"] = standard_ref(meta, d["row_ref"], int(d["stage_row"]))
            if d.get("npis"):
                key = tuple(n for n in d["npis"].split("|") if valid_npi(n))
                d["npi_set"] = set_ids.setdefault(key, len(set_ids) + 1)
                npis[d["npi_set"]] = key
            rows.append(make_row(d))
    dv = doc["data_version"]
    version = DataVersionInfo(
        build_id=str(dv["build_id"]),
        build_date=str(dv["build_date"]),
        tic_release=dv["tic_release"],
    )
    census = {c: list(t) for c, t in (doc.get("census_tins") or {}).items()}
    return rows, sources, version, list(doc.get("codes") or []), npis, census, flags


def pack_from_extract(
    out: Path, csv_path: Path = EXTRACT_CSV, sources_path: Path = EXTRACT_SOURCES
) -> int:
    rows, sources, version, codes, npis, census, flags = read_extract(csv_path, sources_path)
    return write_pack(out, rows=rows, sources=sources, version=version, codes=codes,
                      npi_sets=npis, census_tins=census, flags=flags)  # fmt: skip


def store_from_extract(
    csv_path: Path = EXTRACT_CSV, sources_path: Path = EXTRACT_SOURCES
) -> RateStore:
    """The committed extract through the runtime format (written to a temp pack, then loaded),
    so tests exercise the same loader the server uses."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "quote_pack.sqlite"
        pack_from_extract(p, csv_path, sources_path)
        return load_pack(p)


class ExtractRefused(SystemExit):
    """R11: the server never silently serves the 7,791-row test extract as if it were the data."""


def load_from_env(tins: Iterable[str] | None = None, census_ids: Iterable[str] = ()) -> RateStore:
    """Server startup. ``CARECOST_QUOTE_PACK`` -> that pack (it must exist). Without it, the
    committed test extract only when ``CARECOST_ALLOW_EXTRACT=1`` (tests and dev set it);
    otherwise refuse to start (R11: a missing pack must never look like "no public price")."""
    pack = os.environ.get("CARECOST_QUOTE_PACK")
    if pack:
        p = Path(pack)
        if not p.exists():
            raise ExtractRefused(f"CARECOST_QUOTE_PACK={pack} does not exist")
        return load_pack(p, tins=tins, census_ids=census_ids)
    if os.environ.get("CARECOST_ALLOW_EXTRACT") != "1":
        raise ExtractRefused(
            "no CARECOST_QUOTE_PACK: refusing to serve the test extract (set "
            "CARECOST_ALLOW_EXTRACT=1 for tests and local development)"
        )
    return store_from_extract()
