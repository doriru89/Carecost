"""Parse hospital Machine-Readable Files (MRFs) in 5 formats.

Filters by CPT codes from the registry during parsing (never loads full file).
Supports: standard_csv, cms_v3_csv, cms_json, xlsx, csv_wide.

Public API:
    parse_hospital_rates(file_path, hospital_id, target_cpts) -> list[RawMrfRecord]
    parse_all_hospital_rates(mrf_dir, target_cpts) -> list[RawMrfRecord]
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Iterator

from app.etl.types import RawMrfRecord
from app.registries import get_hospital, load_etl_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_hospital_rates(
    file_path: Path, hospital_id: str, target_cpts: set[str]
) -> list[RawMrfRecord]:
    """Parse a single MRF file, return rows matching the target CPT set."""
    config = load_etl_config()
    sources = config.hospital_mrf_sources

    if hospital_id not in sources:
        raise KeyError(
            f"Unknown hospital MRF source: {hospital_id}. Available: {list(sources.keys())}"
        )

    source = sources[hospital_id]
    fmt = source["format"]
    hospital_name = get_hospital(hospital_id).name

    format_config = config.mrf_formats.get(fmt, {})

    # Merge source-level overrides (e.g. skip_header_rows) into format config
    merged_config = {**format_config, **source}

    dispatch = {
        "standard_csv": _dispatch_standard_csv,
        "cms_v3_csv": _dispatch_cms_v3_csv,
        "cms_json": _dispatch_cms_json,
        "xlsx": _dispatch_xlsx,
        "csv_wide": _dispatch_csv_wide,
    }

    handler = dispatch.get(fmt)
    if handler is None:
        raise ValueError(f"Unknown MRF format: {fmt}")

    records = handler(file_path, target_cpts, hospital_name, merged_config, fmt)
    before = len(records)
    records = _deduplicate_mrf_records(records)
    if before > len(records):
        logger.info(
            "%s: deduplicated %d -> %d records (%d collapsed)",
            hospital_id,
            before,
            len(records),
            before - len(records),
        )
    return records


def parse_all_hospital_rates(mrf_dir: Path, target_cpts: set[str]) -> list[RawMrfRecord]:
    """Parse all MRF files in the directory for the given CPT set.

    Uses hospital_mrf_sources config to find files.
    Logs warnings for missing files but continues processing.
    """
    config = load_etl_config()
    all_records: list[RawMrfRecord] = []

    for hospital_id, source in config.hospital_mrf_sources.items():
        # Try common filename patterns
        fmt = source["format"]
        container = source.get("container", "plain")
        ext = _extension_for_format(fmt, container)
        file_path = mrf_dir / f"{hospital_id}_standardcharges{ext}"

        if not file_path.exists():
            logger.warning("MRF file not found for %s: %s", hospital_id, file_path)
            continue

        try:
            records = parse_hospital_rates(file_path, hospital_id, target_cpts)
            all_records.extend(records)
            logger.info("%s: extracted %d records", hospital_id, len(records))
        except Exception:
            logger.exception("Error parsing MRF for %s", hospital_id)

    return all_records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deduplicate_mrf_records(records: list[RawMrfRecord]) -> list[RawMrfRecord]:
    """Collapse rows sharing (cpt, payer_raw, plan), keeping the best record.

    Hospital MRFs emit multiple rows per (CPT, payer, plan) — chargemaster description
    aliases, facility/professional fee splits, inpatient/outpatient variants. These are
    component-level line items, not distinct prices. We keep the max negotiated_dollar
    (the facility component) as the primary consumer-facing rate. On ties, prefer the
    record with more populated base fields (gross, cash, de_id) to avoid data loss.
    """
    best: dict[tuple[str, str, str], RawMrfRecord] = {}
    for rec in records:
        key = (rec.cpt, rec.payer_raw, rec.plan)
        existing = best.get(key)
        if existing is None:
            best[key] = rec
        else:
            new_rate = rec.negotiated_dollar or 0.0
            old_rate = existing.negotiated_dollar or 0.0
            if new_rate > old_rate:
                best[key] = rec
            elif new_rate == old_rate and _field_richness(rec) > _field_richness(existing):
                best[key] = rec
    return list(best.values())


def _field_richness(rec: RawMrfRecord) -> int:
    """Count non-None base price fields for tiebreaking."""
    return sum(1 for v in (rec.gross, rec.cash, rec.de_id_min, rec.de_id_max) if v is not None)


def _parse_float(val: Any) -> float | None:
    """Safely parse a value to float. Returns None on failure."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _extension_for_format(fmt: str, container: str) -> str:
    if container == "zip":
        return ".zip"
    if fmt == "cms_json":
        return ".json"
    if fmt == "xlsx":
        return ".xlsx"
    return ".csv"


@contextmanager
def _open_mrf_file(
    file_path: Path, source_config: dict
) -> Iterator[tuple[IO[str] | dict | Path, str]]:
    """Open ZIP or plain file based on container config.

    Yields (file_handle_or_data, actual_filename).
    For JSON: yields (parsed_dict, filename).
    For XLSX: yields (file_path, filename) — openpyxl handles its own I/O.
    For CSV: yields (text IO wrapper, filename).
    """
    container = source_config.get("container", "plain")
    encoding = source_config.get("encoding", "utf-8")
    fmt = source_config.get("format", "")

    if container == "zip":
        with zipfile.ZipFile(file_path) as zf:
            # Find the right file inside the ZIP (skip __MACOSX)
            names = [
                n for n in zf.namelist() if not n.startswith("__MACOSX") and not n.startswith(".")
            ]
            if not names:
                yield io.StringIO(""), file_path.name
                return
            inner_name = names[0]

            with zf.open(inner_name) as raw:
                if fmt == "cms_json":
                    data = json.load(io.TextIOWrapper(raw, encoding=encoding))
                    yield data, inner_name
                elif fmt == "xlsx":
                    # Write to tmp for openpyxl
                    import tempfile

                    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                        tmp.write(raw.read())
                        tmp_path = Path(tmp.name)
                    try:
                        yield tmp_path, inner_name
                    finally:
                        tmp_path.unlink(missing_ok=True)
                else:
                    yield io.TextIOWrapper(raw, encoding=encoding), inner_name
    else:
        if fmt == "cms_json":
            with open(file_path, encoding=encoding) as f:
                data = json.load(f)
            yield data, file_path.name
        elif fmt == "xlsx":
            yield file_path, file_path.name
        else:
            with open(file_path, encoding=encoding) as f:
                yield f, file_path.name


# ---------------------------------------------------------------------------
# Format dispatchers (open file, call parser)
# ---------------------------------------------------------------------------


def _dispatch_standard_csv(
    file_path: Path,
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    fmt: str,
) -> list[RawMrfRecord]:
    with _open_mrf_file(file_path, config) as (fh, _):
        if isinstance(fh, io.StringIO) and fh.getvalue() == "":
            return []
        reader = csv.reader(fh)  # type: ignore[arg-type]
        return _parse_standard_csv(reader, cpt_codes, hospital_name, config, str(file_path), fmt)


def _dispatch_cms_v3_csv(
    file_path: Path,
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    fmt: str,
) -> list[RawMrfRecord]:
    with _open_mrf_file(file_path, config) as (fh, _):
        if isinstance(fh, io.StringIO) and fh.getvalue() == "":
            return []
        reader = csv.reader(fh)  # type: ignore[arg-type]
        return _parse_cms_v3_csv(reader, cpt_codes, hospital_name, config, str(file_path), fmt)


def _dispatch_cms_json(
    file_path: Path,
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    fmt: str,
) -> list[RawMrfRecord]:
    with _open_mrf_file(file_path, config) as (data, _):
        if isinstance(data, (io.StringIO, str)):
            return []
        return _parse_cms_json(
            data,
            cpt_codes,
            hospital_name,
            config,
            str(file_path),
            fmt,  # type: ignore[arg-type]
        )


def _dispatch_xlsx(
    file_path: Path,
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    fmt: str,
) -> list[RawMrfRecord]:
    with _open_mrf_file(file_path, config) as (xlsx_path, _):
        return _parse_xlsx(
            xlsx_path,
            cpt_codes,
            hospital_name,
            config,
            str(file_path),
            fmt,  # type: ignore[arg-type]
        )


def _dispatch_csv_wide(
    file_path: Path,
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    fmt: str,
) -> list[RawMrfRecord]:
    with _open_mrf_file(file_path, config) as (fh, _):
        if isinstance(fh, io.StringIO) and fh.getvalue() == "":
            return []
        reader = csv.reader(fh)  # type: ignore[arg-type]
        return _parse_csv_wide(reader, cpt_codes, hospital_name, config, str(file_path), fmt)


# ---------------------------------------------------------------------------
# Internal parsers
# ---------------------------------------------------------------------------


def _parse_standard_csv(
    reader: Iterator[list[str]],
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    source_file: str,
    fmt: str,
) -> list[RawMrfRecord]:
    """MGB system: fixed column indices from etl_config.

    Indices: 0=description, 3=cpt, 4=cpt_desc, 5=description,
    9=setting, 12=gross, 13=cash, 14=payer, 15=plan,
    17=negotiated_dollar, 18=estimated_amount, 19=min, 20=max.
    """
    skip = config.get("skip_header_rows", 0)
    results: list[RawMrfRecord] = []

    for i, row in enumerate(reader):
        if i < skip:
            continue
        if len(row) < 15:
            continue

        cpt = row[3].strip()
        if cpt not in cpt_codes:
            continue

        results.append(
            RawMrfRecord(
                hospital_name=hospital_name,
                cpt=cpt,
                cpt_desc=row[4].strip() if len(row) > 4 else "",
                description=row[0].strip(),
                payer_raw=row[14].strip(),
                plan=row[15].strip() if len(row) > 15 else "",
                setting=row[9].strip() if len(row) > 9 else "",
                gross=_parse_float(row[12]) if len(row) > 12 else None,
                cash=_parse_float(row[13]) if len(row) > 13 else None,
                negotiated_dollar=_parse_float(row[17]) if len(row) > 17 else None,
                estimated_amount=_parse_float(row[18]) if len(row) > 18 else None,
                de_id_min=_parse_float(row[19]) if len(row) > 19 else None,
                de_id_max=_parse_float(row[20]) if len(row) > 20 else None,
                billing_class="",
                source_file=source_file,
                mrf_format=fmt,
            )
        )

    return results


def _parse_cms_v3_csv(
    reader: Iterator[list[str]],
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    source_file: str,
    fmt: str,
) -> list[RawMrfRecord]:
    """Dynamic code|N headers. Long format (one row per payer).

    Skip metadata rows, find header with 'description' in first column,
    then map columns dynamically.
    """
    skip = config.get("skip_header_rows", 0)
    results: list[RawMrfRecord] = []

    # Skip metadata rows, then find header
    header: list[str] | None = None
    for i, row in enumerate(reader):
        if i < skip:
            continue
        # Header row: first cell starts with "description" (case-insensitive)
        if row and row[0].strip().lower() == "description":
            header = [c.strip().lower() for c in row]
            break
        # Safety: don't scan forever
        if i > skip + 20:
            break

    if header is None:
        return results

    h = {col: idx for idx, col in enumerate(header)}

    def _get(row: list[str], col: str) -> str:
        idx = h.get(col, -1)
        if 0 <= idx < len(row):
            return row[idx].strip()
        return ""

    for row in reader:
        if len(row) < 10:
            continue

        # Find CPT code from code|N columns
        cpt = ""
        for code_key in ("code|2", "code|1", "code|3", "code|4"):
            val = _get(row, code_key)
            type_val = _get(row, f"{code_key}|type").upper()
            if val in cpt_codes and type_val in ("CPT", "HCPCS", ""):
                cpt = val
                break

        if not cpt:
            continue

        desc = _get(row, "description")
        results.append(
            RawMrfRecord(
                hospital_name=hospital_name,
                cpt=cpt,
                cpt_desc=desc,
                description=desc,
                payer_raw=_get(row, "payer_name"),
                plan=_get(row, "plan_name"),
                setting=_get(row, "setting"),
                gross=_parse_float(_get(row, "standard_charge|gross")),
                cash=_parse_float(_get(row, "standard_charge|discounted_cash")),
                negotiated_dollar=_parse_float(_get(row, "standard_charge|negotiated_dollar")),
                estimated_amount=_parse_float(
                    _get(row, "median_amount") or _get(row, "estimated_amount")
                ),
                de_id_min=_parse_float(_get(row, "standard_charge|min")),
                de_id_max=_parse_float(_get(row, "standard_charge|max")),
                billing_class="",
                source_file=source_file,
                mrf_format=fmt,
            )
        )

    return results


def _parse_cms_json(
    data: dict,
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    source_file: str,
    fmt: str,
) -> list[RawMrfRecord]:
    """Navigate standard_charge_information[].code_information[].code."""
    results: list[RawMrfRecord] = []

    for item in data.get("standard_charge_information", []):
        # Check if any code matches our CPT set
        codes = item.get("code_information", [])
        matched_cpt = ""
        for code_info in codes:
            code = str(code_info.get("code", "")).strip()
            code_type = str(code_info.get("type", "")).upper()
            if code in cpt_codes and code_type in ("CPT", "HCPCS", ""):
                matched_cpt = code
                break

        if not matched_cpt:
            continue

        description = item.get("description", "")

        for charge in item.get("standard_charges", []):
            payer = charge.get("payer_name", "")
            if not payer:
                # Infer from charge type
                if "gross_charge" in charge and charge["gross_charge"]:
                    payer = "GROSS"
                else:
                    payer = "CASH"

            results.append(
                RawMrfRecord(
                    hospital_name=hospital_name,
                    cpt=matched_cpt,
                    cpt_desc=description,
                    description=description,
                    payer_raw=payer,
                    plan=charge.get("plan_name", "") or "",
                    setting=charge.get("setting", "") or "",
                    gross=_parse_float(charge.get("gross_charge")),
                    cash=_parse_float(charge.get("discounted_cash")),
                    negotiated_dollar=_parse_float(
                        charge.get("standard_charge_dollar") or charge.get("negotiated_dollar")
                    ),
                    estimated_amount=_parse_float(charge.get("estimated_amount")),
                    de_id_min=_parse_float(charge.get("minimum")),
                    de_id_max=_parse_float(charge.get("maximum")),
                    billing_class="",
                    source_file=source_file,
                    mrf_format=fmt,
                )
            )

    return results


def _parse_xlsx(
    file_path: Path,
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    source_file: str,
    fmt: str,
) -> list[RawMrfRecord]:
    """openpyxl read-only. Lazy import. Find header by scanning for CPT column."""
    try:
        import openpyxl
    except ImportError:
        logger.warning("openpyxl not installed, skipping XLSX parsing")
        return []

    wb = openpyxl.load_workbook(file_path, read_only=True)
    ws = wb.active
    if ws is None:
        logger.warning("No active worksheet in %s", file_path)
        return []
    results: list[RawMrfRecord] = []
    header: list[str] | None = None

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if header is None:
            # Look for header row containing a CPT column identifier
            row_strs = [str(c or "").strip().lower() for c in row]
            if any("cpt" in cell or "billing_cd" in cell or "hcpcs" in cell for cell in row_strs):
                header = row_strs
                continue
            # Don't scan forever
            if i > 20:
                break
            continue

        row_dict = dict(zip(header, row))

        # Determine CPT code
        cpt = ""
        # Try various column names
        for col in ("cpt/hcpcs code", "billing_cd", "cpt", "hcpcs", "code"):
            val = str(row_dict.get(col, "") or "").strip()
            if val in cpt_codes:
                cpt = val
                break

        # If billing_cd, check type
        if not cpt and "billing_cd" in row_dict:
            code_type = str(row_dict.get("billing_cd_type_nm", "") or "").upper()
            if code_type in ("CPT", "HCPCS"):
                val = str(row_dict.get("billing_cd", "") or "").strip()
                if val in cpt_codes:
                    cpt = val

        if not cpt:
            continue

        results.append(
            RawMrfRecord(
                hospital_name=hospital_name,
                cpt=cpt,
                cpt_desc="",
                description=str(
                    row_dict.get("billing_description", "") or row_dict.get("description", "") or ""
                ),
                payer_raw=str(row_dict.get("payer", "") or ""),
                plan=str(row_dict.get("plan", "") or ""),
                setting=str(
                    row_dict.get("class_nm", "") or row_dict.get("setting", "") or ""
                ).lower(),
                gross=_parse_float(row_dict.get("gross_chg_amt") or row_dict.get("gross_charge")),
                cash=_parse_float(row_dict.get("disc_chg_amt") or row_dict.get("discounted_cash")),
                negotiated_dollar=_parse_float(
                    row_dict.get("payer_chg_amt") or row_dict.get("negotiated_dollar")
                ),
                estimated_amount=None,
                de_id_min=_parse_float(row_dict.get("min_chg_amt") or row_dict.get("minimum")),
                de_id_max=_parse_float(row_dict.get("max_chg_amt") or row_dict.get("maximum")),
                billing_class="",
                source_file=source_file,
                mrf_format=fmt,
            )
        )

    wb.close()
    return results


def _parse_csv_wide(
    reader: Iterator[list[str]],
    cpt_codes: set[str],
    hospital_name: str,
    config: dict,
    source_file: str,
    fmt: str,
) -> list[RawMrfRecord]:
    """Headers like standard_charge|<Payer>|<Plan>|negotiated_dollar.

    Unpivot: one RawMrfRecord per payer column with a non-empty value.
    """
    results: list[RawMrfRecord] = []

    # Find header row
    header: list[str] | None = None
    skip = config.get("skip_header_rows", 0)
    for i, row in enumerate(reader):
        if i < skip:
            continue
        # Header: first cell is "description" (case-insensitive)
        if row and row[0].strip().lower() == "description":
            header = [c.strip() for c in row]
            break
        if i > skip + 20:
            break

    if header is None:
        return results

    h = {col: idx for idx, col in enumerate(header)}
    h_lower = {col.lower(): idx for idx, col in enumerate(header)}

    # Find payer columns: standard_charge|<Payer>|<Plan>|negotiated_dollar
    payer_cols: list[tuple[int, str, str]] = []
    for col_name, idx in h.items():
        if col_name.startswith("standard_charge|") and col_name.endswith("|negotiated_dollar"):
            parts = col_name.split("|")
            if len(parts) >= 4:
                payer = parts[1]
                plan = parts[2]
                payer_cols.append((idx, payer, plan))

    # Common column indices
    gross_idx = h_lower.get("standard_charge|gross", -1)
    cash_idx = h_lower.get("standard_charge|discounted_cash", -1)
    min_idx = h_lower.get("standard_charge|min", -1)
    max_idx = h_lower.get("standard_charge|max", -1)
    desc_idx = h_lower.get("description", -1)
    setting_idx = h_lower.get("setting", -1)

    def _safe(row: list[str], idx: int) -> str:
        return row[idx].strip() if 0 <= idx < len(row) else ""

    for row in reader:
        if len(row) < 5:
            continue

        # Find CPT from code|N columns
        cpt = ""
        for code_key in ("code|2", "code|1", "code|3", "code|4"):
            idx = h_lower.get(code_key, -1)
            type_idx = h_lower.get(f"{code_key}|type", -1)
            if 0 <= idx < len(row):
                val = row[idx].strip()
                code_type = row[type_idx].strip().upper() if 0 <= type_idx < len(row) else ""
                if val in cpt_codes and code_type in ("CPT", "HCPCS", ""):
                    cpt = val
                    break

        if not cpt:
            continue

        desc = _safe(row, desc_idx)
        setting = _safe(row, setting_idx)
        gross = _parse_float(_safe(row, gross_idx))
        cash = _parse_float(_safe(row, cash_idx))
        min_val = _parse_float(_safe(row, min_idx))
        max_val = _parse_float(_safe(row, max_idx))

        # One record per payer column with non-empty value
        for col_idx, payer, plan in payer_cols:
            if col_idx >= len(row):
                continue
            neg_dollar_str = row[col_idx].strip()
            if not neg_dollar_str:
                continue

            results.append(
                RawMrfRecord(
                    hospital_name=hospital_name,
                    cpt=cpt,
                    cpt_desc="",
                    description=desc,
                    payer_raw=payer,
                    plan=plan,
                    setting=setting,
                    gross=gross,
                    cash=cash,
                    negotiated_dollar=_parse_float(neg_dollar_str),
                    estimated_amount=None,
                    de_id_min=min_val,
                    de_id_max=max_val,
                    billing_class="",
                    source_file=source_file,
                    mrf_format=fmt,
                )
            )

    return results
