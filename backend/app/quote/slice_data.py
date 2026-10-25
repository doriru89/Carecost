"""Rate rows for the quote engine, loaded once at startup into in-memory dicts (no per-request DB).

Two ways to fill the same ``SliceData``:

* ``load_from_build``: the real local data. Hospital MRF rows from an ETL build's
  ``rate_row.sqlite`` (stdlib) and insurer TiC rows from ``<tic_root>/<source_id>/CURRENT``
  ``rate_row.parquet`` (needs pyarrow, the ``etl`` extra). Only the codes and TINs in scope are
  read. Freshness inputs come from the build ``manifest.json`` and each TiC ``run.json``.
* ``load_from_extract``: the small committed extract (``contracts/fixtures/rate_row_extract.csv``
  + ``rate_row_extract.sources.yaml``), so tests and CI need none of the 1 GB of data.

Indexes (what a quote looks up):

* ``hospital[(source_id, code, payer_id)]``: that hospital file's rows for one code and payer
  (``""`` for chargemaster rows and unmapped payers);
* ``cash[(source_id, code)]``: rows with a discounted cash price, one row per distinct
  (modifiers, component, setting, cash, gross), keeping the lowest stage_row. Tall CSV files
  repeat the hospital-wide cash price on every payer row, so this keeps the index small;
* ``tic[(source_id, tin, code)]``: TiC rows for one billing TIN (9 digits) and code.

``Recorder`` collects every row a lookup returned, so the fixture generator can write an extract
that reproduces the same quotes exactly.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.etl.contracts import Method, PriceBasis, Provenance, SourceKind

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "data" / "quote" / "p1_slice.yaml"
EXTRACT_CSV = REPO_ROOT / "contracts" / "fixtures" / "rate_row_extract.csv"
EXTRACT_SOURCES = REPO_ROOT / "contracts" / "fixtures" / "rate_row_extract.sources.yaml"


@dataclass(frozen=True, slots=True)
class Row:
    """The rate_row columns the quote engine reads (hospital MRF and TiC rows alike)."""

    row_ref: str
    row_id: str  # unique per build; row_ref is NOT unique (one TiC price row serves many groups)
    source_id: str
    source_kind: str
    row_kind: str
    code: str
    modifiers: str
    component: str
    billing_class: str
    setting: str
    payer_id: str | None
    product: str
    line_of_business: str
    payer_raw: str
    plan_raw: str
    amount: float | None
    amount_method: str
    negotiated_pct: float | None
    discounted_cash: float | None
    gross: float | None
    excluded: bool
    source_file: str
    source_sha256: str
    source_date: str | None
    stage_row: int
    tin: str = ""  # TiC billing TIN, digits only
    service_codes: str = ""  # TiC place-of-service codes, '|'-joined
    business_name: str = ""
    negotiated_type: str = ""
    provider_group_id: str = ""

    @property
    def uid(self) -> str:
        """In-memory key. A TiC price row (one row_ref) applies to every provider group listed
        with it, and a hospital line with two target codes gives two rows with one row_ref."""
        return f"{self.source_id}:{self.row_id}"

    def prov(self, basis: PriceBasis) -> Provenance:
        method = (
            Method.derived_pct_x_gross
            if self.amount_method == "derived_pct_x_gross"
            else (Method.stated)
        )
        return Provenance(
            source_id=self.source_id,
            source_kind=SourceKind(self.source_kind),
            source_file=self.source_file,
            source_sha256=self.source_sha256,
            source_date=date.fromisoformat(self.source_date) if self.source_date else None,
            method=method,
            row_ref=self.row_ref,
            # a negotiated rate is a payer's; a cash price or gross charge belongs to no payer
            payer_id=self.payer_id if basis == PriceBasis.negotiated else None,
        )


ROW_COLUMNS = [f.name for f in fields(Row)]


@dataclass(frozen=True)
class SourceMeta:
    """Freshness inputs for one source, stored once (P2)."""

    source_id: str
    source_kind: str
    publisher: str
    source_file: str
    source_sha256: str
    last_updated: str | None  # publisher's own date (ISO)
    fetched_at: str  # our last successful fetch (ISO date)


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
class SliceData:
    rows: dict[str, Row]
    sources: dict[str, SourceMeta]
    version: DataVersionInfo
    hospital: dict[tuple[str, str, str], list[Row]] = field(default_factory=dict)
    cash: dict[tuple[str, str], list[Row]] = field(default_factory=dict)
    tic: dict[tuple[str, str, str], list[Row]] = field(default_factory=dict)
    recorder: Recorder | None = None

    def __post_init__(self) -> None:
        self._index()

    def _index(self) -> None:
        hosp: dict[tuple[str, str, str], list[Row]] = defaultdict(list)
        cash_best: dict[tuple, Row] = {}
        tic: dict[tuple[str, str, str], list[Row]] = defaultdict(list)
        for r in sorted(self.rows.values(), key=lambda r: (r.source_id, r.stage_row, r.row_id)):
            if r.source_kind == "hospital_mrf":
                hosp[(r.source_id, r.code, r.payer_id or "")].append(r)
                if r.discounted_cash is not None:
                    k = (r.source_id, r.code, r.modifiers, r.component, r.setting,
                         r.discounted_cash, r.gross)  # fmt: skip
                    cash_best.setdefault(k, r)  # rows are sorted: first = lowest stage_row
            elif r.source_kind == "insurer_tic":
                tic[(r.source_id, r.tin, r.code)].append(r)
        cash: dict[tuple[str, str], list[Row]] = defaultdict(list)
        for k, r in cash_best.items():
            cash[(k[0], k[1])].append(r)
        self.hospital = dict(hosp)
        self.cash, self.tic = dict(cash), dict(tic)

    def get(self, index: str, key: tuple) -> list[Row]:
        rows = getattr(self, index).get(key, [])
        if self.recorder is not None:
            self.recorder.add(rows)
        return rows

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for r in self.rows.values():
            out[r.source_id] += 1
        return dict(sorted(out.items()))


# --------------------------------------------------------------------------- config


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def scope_codes(path_codes: Iterable[str]) -> list[str]:
    return sorted(set(path_codes))


# --------------------------------------------------------------------------- converters


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    return float(v)


def _s(v: Any) -> str:
    return "" if v is None else str(v)


def _tin(v: Any) -> str:
    return "".join(ch for ch in _s(v) if ch.isdigit())


def _row(d: dict[str, Any]) -> Row:
    return Row(
        row_ref=_s(d["row_ref"]),
        row_id=_s(d["row_id"]),
        source_id=_s(d["source_id"]),
        source_kind=_s(d["source_kind"]),
        row_kind=_s(d["row_kind"]),
        code=_s(d["code"]),
        modifiers=_s(d["modifiers"]),
        component=_s(d["component"]),
        billing_class=_s(d["billing_class"]),
        setting=_s(d["setting"]),
        payer_id=d["payer_id"] or None,
        product=_s(d["product"]),
        line_of_business=_s(d["line_of_business"]),
        payer_raw=_s(d["payer_raw"]),
        plan_raw=_s(d["plan_raw"]),
        amount=_f(d["amount"]),
        amount_method=_s(d["amount_method"]),
        negotiated_pct=_f(d["negotiated_pct"]),
        discounted_cash=_f(d["discounted_cash"]),
        gross=_f(d["gross"]),
        excluded=str(d["excluded"]) in ("1", "True", "true"),
        source_file=_s(d["source_file"]),
        source_sha256=_s(d["source_sha256"]),
        source_date=_s(d["source_date"])[:10] or None,
        stage_row=int(d["stage_row"]),
        tin=_tin(d.get("tin") if "tin" in d else d.get("tic_tin_value")),
        service_codes=_s(d.get("service_codes") if "service_codes" in d else d.get("tic_service_codes")),
        business_name=_s(d.get("business_name") if "business_name" in d else d.get("tic_business_name")),
        negotiated_type=_s(
            d.get("negotiated_type") if "negotiated_type" in d else d.get("tic_negotiated_type")
        ),
        provider_group_id=_s(
            d.get("provider_group_id") if "provider_group_id" in d else d.get("tic_provider_group_id")
        ),
    )  # fmt: skip


_HOSPITAL_SQL_COLS = [
    "row_ref", "row_id", "source_id", "source_kind", "row_kind", "code", "modifiers", "component",
    "billing_class", "setting", "payer_id", "product", "line_of_business", "payer_raw", "plan_raw",
    "amount", "amount_method", "negotiated_pct", "discounted_cash", "gross", "excluded",
    "source_file", "source_sha256", "source_date", "stage_row",
]  # fmt: skip
_TIC_COLS = [*_HOSPITAL_SQL_COLS, "tic_tin_value", "tic_service_codes", "tic_business_name",
             "tic_negotiated_type", "tic_provider_group_id"]  # fmt: skip


# --------------------------------------------------------------------------- real data


def _date(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).date().isoformat()


def load_from_build(
    *,
    hospital_build: Path,
    tic_root: Path,
    hospital_sources: list[str],
    tic_sources: list[str],
    tins: list[str],
    codes: list[str],
    publishers: dict[str, str],
) -> SliceData:
    """Read only the rows in scope from the real build (hospital) and TiC intermediates."""
    manifest = json.loads((hospital_build / "manifest.json").read_text())
    rows: dict[str, Row] = {}
    sources: dict[str, SourceMeta] = {}

    db = sqlite3.connect(f"file:{hospital_build / 'rate_row.sqlite'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    q_src = ",".join("?" * len(hospital_sources))
    q_code = ",".join("?" * len(codes))
    sql = (
        f"select {', '.join(_HOSPITAL_SQL_COLS)} from rate_row "
        f"where source_id in ({q_src}) and code in ({q_code})"
    )
    for rec in db.execute(sql, [*hospital_sources, *codes]):
        r = _row(dict(rec))
        rows[r.uid] = r
    db.close()
    for sid in hospital_sources:
        m = manifest["sources"].get(sid)
        if m is None:
            raise SystemExit(f"{sid} is not in {hospital_build}/manifest.json")
        sources[sid] = SourceMeta(
            source_id=sid,
            source_kind="hospital_mrf",
            publisher=publishers[sid],
            source_file=m["raw_file"],
            source_sha256=m["sha256"],
            last_updated=m.get("last_updated_on"),
            fetched_at=_date(m["fetched_at"]),
        )

    tic_release = None
    if tic_sources:
        import pyarrow.parquet as pq  # etl extra; only the real-data path needs it

        want_tins = set(tins)
        for sid in tic_sources:
            sha = (tic_root / sid / "CURRENT").read_text().strip()
            d = tic_root / sid / sha
            run = json.loads((d / "run.json").read_text())
            table = pq.read_table(
                d / "rate_row.parquet",
                columns=_TIC_COLS,
                filters=[("code", "in", codes)],
            )
            for rec in table.to_pylist():
                if _tin(rec["tic_tin_value"]) not in want_tins:
                    continue
                r = _row(rec)
                rows[r.uid] = r
            sources[sid] = SourceMeta(
                source_id=sid,
                source_kind="insurer_tic",
                publisher=publishers[sid],
                source_file=run["fetch"]["local_copy"],
                source_sha256=run["normalize"]["source_sha256"],
                last_updated=run.get("last_updated_on"),
                fetched_at=_date(run["fetch"]["fetched_at"]),
            )
            rel = "tic-" + run["last_updated_on"][:7]
            if tic_release not in (None, rel):
                raise SystemExit(f"TiC files from two releases: {tic_release} vs {rel}")
            tic_release = rel
    version = DataVersionInfo(
        build_id=manifest["build_id"], build_date=manifest["build_date"], tic_release=tic_release
    )
    return SliceData(rows=rows, sources=sources, version=version)


# --------------------------------------------------------------------------- committed extract


def _csv_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


def write_extract(
    data: SliceData, refs: Iterable[str], csv_path: Path, sources_path: Path, extra_rows=()
) -> int:
    """Write the rows in ``refs`` (+ ``extra_rows`` dicts in the same columns) and the sources."""
    out = sorted({data.rows[u] for u in refs}, key=lambda r: (r.source_id, r.stage_row, r.row_id))
    seen = {r.uid for r in out}
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, ROW_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in out:
            w.writerow({c: _csv_value(getattr(r, c)) for c in ROW_COLUMNS})
        for d in extra_rows:
            uid = f"{d['source_id']}:{d['row_id']}"
            if uid not in seen:
                w.writerow({c: _csv_value(d.get(c)) for c in ROW_COLUMNS})
                seen.add(uid)
    doc = {
        "version": 1,
        "note": "Freshness inputs for the sources in rate_row_extract.csv. Written by "
        "python -m app.quote.fixtures_gen; do not edit by hand.",
        "data_version": {
            "build_id": data.version.build_id,
            "build_date": data.version.build_date,
            "tic_release": data.version.tic_release,
        },
        "sources": {
            sid: {k: v for k, v in m.__dict__.items() if k != "source_id"}
            for sid, m in sorted(data.sources.items())
        },
    }
    sources_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return len(seen)


def load_from_extract(
    csv_path: Path = EXTRACT_CSV, sources_path: Path = EXTRACT_SOURCES
) -> SliceData:
    with csv_path.open() as f:
        rows = {r.uid: r for r in (_row(d) for d in csv.DictReader(f))}
    doc = yaml.safe_load(sources_path.read_text())
    sources = {sid: SourceMeta(source_id=sid, **m) for sid, m in doc["sources"].items()}
    dv = doc["data_version"]
    version = DataVersionInfo(
        build_id=dv["build_id"], build_date=str(dv["build_date"]), tic_release=dv["tic_release"]
    )
    # only the sources the engine prices with (the extract also carries rows other fixtures cite)
    return SliceData(rows=rows, sources=sources, version=version)


def load_from_env() -> SliceData:
    """Server startup. CARECOST_HOSPITAL_BUILD + CARECOST_TIC_ROOT -> real data; otherwise the
    committed extract (or CARECOST_EXTRACT_CSV / CARECOST_EXTRACT_SOURCES)."""
    from app.quote.engine import Engine

    build = os.environ.get("CARECOST_HOSPITAL_BUILD")
    if build:
        tic_root = os.environ.get("CARECOST_TIC_ROOT")
        if not tic_root:
            raise SystemExit("CARECOST_HOSPITAL_BUILD needs CARECOST_TIC_ROOT too")
        return Engine.load_real(Path(build), Path(tic_root))
    return load_from_extract(
        Path(os.environ.get("CARECOST_EXTRACT_CSV", EXTRACT_CSV)),
        Path(os.environ.get("CARECOST_EXTRACT_SOURCES", EXTRACT_SOURCES)),
    )
