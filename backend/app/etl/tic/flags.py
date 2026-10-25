"""TiC row flags from O's outlier audit (A6), computed per network file after ``tic normalize``.

A flag is not an exclusion: the row stays a price, but it carries a fact the engine must know
before it uses the row. ``RateRow`` (C3's contract) has no flags column, so the flags live next
to the run's ``rate_row.parquet`` in ``flags.parquet`` (``row_id``, ``flags`` = '|'-joined,
sorted) and are counted in ``run.json`` ``flags``. The pack can join them on ``row_id``.

* ``anesthesia_per_unit``: an anesthesia code (CMS base-units file) whose TIN lists the same
  amount on another anesthesia code with *different* CMS base units. One amount on 00811 (4
  units), 00812 (3) and 00813 (5) is a conversion factor per unit, not a case price (MGB
  "SYNERGY SURGICALISTS" $20.98 on all three).
* ``institutional_on_physician_npi``: ``billing_class: institutional`` on a provider group that
  is one NPI, and NPPES says that NPI is a person (NPI-1) or a physician-group organisation
  (``data/etl/tic_npi_types.yaml``, ``tic npi-types``). A doctors' group's "institutional" rate is
  not a hospital facility fee (Tufts Direct "BOSTON SPECIALISTS - SOUTH SHO" $81.06 on 45378).
* ``same_npi_pos_multi_rate``: two or more different amounts for the same TIN, the same NPI set,
  code, modifiers, billing class, setting, POS list and negotiated type, from different provider groups or
  rate groups (Aetna PPO 11102 "Metrowest Physician Services" $254.73 and $123.69). The source
  itself is ambiguous: these rows also get ``ambiguous_multi_rate = true`` in ``rate_row``.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import yaml

from app.etl.config import CONFIG_DIR
from app.etl.tic.index import atomic_write_table

FLAGS = ("anesthesia_per_unit", "institutional_on_physician_npi", "same_npi_pos_multi_rate")
NPI_TYPES_FILE = "tic_npi_types.yaml"
FLAGS_SCHEMA = pa.schema([pa.field("row_id", pa.string()), pa.field("flags", pa.string())])


def load_npi_types(config_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    f = (config_dir or CONFIG_DIR) / NPI_TYPES_FILE
    if not f.exists():
        return {}
    return (yaml.safe_load(f.read_text()) or {}).get("npis") or {}


_FACILITY_NAME = re.compile(
    r"SURGERY CENTER|SURGICAL CENTER|SURGICENTER|ENDOSCOPY|\bASC\b|HOSPITAL", re.I
)


def is_physician(rec: dict[str, Any] | None) -> bool:
    """NPPES: a person, or an organisation whose primary taxonomy is a physician group and
    whose name does not say it is a facility ("MEDFORD SURGERY CENTER LLC" lists taxonomy
    Surgery but bills an ASC facility fee)."""
    if not rec:
        return False
    if rec.get("type") == "NPI-1":
        return True
    return bool(rec.get("physician_group")) and not _FACILITY_NAME.search(rec.get("name") or "")


def _group_npis(d: Path) -> dict[tuple[int, int], tuple[str, ...]]:
    t = pq.read_table(d / "groups.parquet", columns=["provider_group_id", "group_ordinal", "npis"])
    return {
        (r["provider_group_id"], r["group_ordinal"]): tuple(sorted(r["npis"] or ()))
        for r in t.to_pylist()
    }


def single_npi(r: dict[str, Any], gnpis: dict[tuple[int, int], tuple[str, ...]]) -> str:
    """The one NPI a provider group is ('' when it is several or unknown)."""
    if (r["tic_tin_type"] or "").lower() == "npi":
        return "".join(ch for ch in r["tic_tin_value"] or "" if ch.isdigit())
    got = gnpis.get((r["tic_provider_group_id"], r["tic_group_ordinal"])) or ()
    return got[0] if len(got) == 1 else ""


_COLS = [
    "row_id", "code", "modifiers", "billing_class", "setting", "amount", "tic_tin_value", "tic_tin_type",
    "tic_provider_group_id", "tic_group_ordinal", "tic_rate_group_ordinal", "tic_service_codes",
    "tic_negotiated_type", "excluded",
]  # fmt: skip


def compute(
    d: Path, base_units: dict[str, int], npi_types: dict[str, dict[str, Any]]
) -> tuple[dict[str, set[str]], Counter[str], set[str]]:
    """-> (row_id -> flags, flag -> rows, NPIs of single-NPI institutional rows)."""
    rows = pq.read_table(d / "rate_row.parquet", columns=_COLS).to_pylist()
    gnpis = _group_npis(d)
    out: dict[str, set[str]] = defaultdict(set)
    singles: set[str] = set()

    # anesthesia per unit: tin x amount -> the base units of the codes that carry it
    anes: dict[tuple[str, float], set[int]] = defaultdict(set)
    rows = [r for r in rows if not r["excluded"]]
    for r in rows:
        if r["code"] in base_units and r["amount"] is not None:
            anes[(r["tic_tin_value"], r["amount"])].add(base_units[r["code"]])
    # same NPI set + POS, several amounts
    dup: dict[str, set[float]] = defaultdict(set)
    dup_key: dict[str, str] = {}
    for r in rows:
        if r["amount"] is not None and r["code"] in base_units:
            if len(anes[(r["tic_tin_value"], r["amount"])]) > 1:
                out[r["row_id"]].add("anesthesia_per_unit")
        if r["billing_class"] == "facility":
            n = single_npi(r, gnpis)
            if n:
                singles.add(n)
                if is_physician(npi_types.get(n)):
                    out[r["row_id"]].add("institutional_on_physician_npi")
        if r["amount"] is None:
            continue
        npis = gnpis.get((r["tic_provider_group_id"], r["tic_group_ordinal"])) or ()
        if not npis:
            continue  # NPIs unknown: "same NPIs" cannot be shown
        parts = [
            r["tic_tin_value"] or "", r["code"], r["modifiers"], r["billing_class"],
            r["setting"] or "", r["tic_service_codes"] or "", (r["tic_negotiated_type"] or "").lower(),
            hashlib.sha1("|".join(npis).encode()).hexdigest(),
        ]  # fmt: skip
        k = "\x1f".join(parts)
        dup[k].add(r["amount"])
        dup_key[r["row_id"]] = k
    for rid, k in dup_key.items():
        if len(dup[k]) > 1:
            out[rid].add("same_npi_pos_multi_rate")
    counts: Counter[str] = Counter(f for fs in out.values() for f in fs)
    return dict(out), counts, singles


def apply(
    d: Path, base_units: dict[str, int], npi_types: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Write ``d/flags.parquet``; set ``ambiguous_multi_rate`` on same-NPI duplicates in
    ``d/rate_row.parquet``. -> stats for run.json."""
    flags, counts, singles = compute(d, base_units, npi_types)
    t = pa.Table.from_pylist(
        [{"row_id": k, "flags": "|".join(sorted(v))} for k, v in sorted(flags.items())],
        FLAGS_SCHEMA,
    )
    atomic_write_table(t, d / "flags.parquet")
    dups = {k for k, v in flags.items() if "same_npi_pos_multi_rate" in v}
    if dups:
        rr = pq.read_table(d / "rate_row.parquet")
        hit = pc.is_in(rr.column("row_id"), value_set=pa.array(sorted(dups)))
        amb = pc.or_(rr.column("ambiguous_multi_rate"), hit)
        i = rr.schema.get_field_index("ambiguous_multi_rate")
        rr = rr.set_column(i, rr.schema.field(i), amb)
        atomic_write_table(rr, d / "rate_row.parquet")
    return {
        "rows_flagged": len(flags),
        "by_flag": {f: counts.get(f, 0) for f in FLAGS},
        "single_npi_institutional_npis": len(singles),
        "single_npi_institutional_npis_unknown_type": len(singles - set(npi_types)),
    }


def load_flags(d: Path) -> dict[str, list[str]]:
    f = d / "flags.parquet"
    if not f.exists():
        return {}
    return {r["row_id"]: r["flags"].split("|") for r in pq.read_table(f).to_pylist()}


def single_npis(d: Path) -> set[str]:
    """NPIs that are the only NPI of a group with an institutional row (for ``tic npi-types``)."""
    cols = ["billing_class", "tic_tin_value", "tic_tin_type", "tic_provider_group_id",
            "tic_group_ordinal"]  # fmt: skip
    rows = pq.read_table(
        d / "rate_row.parquet", columns=cols, filters=[("billing_class", "=", "facility")]
    ).to_pylist()
    g = _group_npis(d)
    return {n for r in rows if (n := single_npi(r, g))}
