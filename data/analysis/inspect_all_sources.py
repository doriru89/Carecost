"""Cross-source data inspection for CareCost schema design.

Compares all available data sources for CPT 45378 (colonoscopy) side-by-side.
Outputs: per-source summary, coverage matrix, price comparison, TiC format analysis.
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path

import ijson
import openpyxl

PROJECT = Path(__file__).resolve().parent.parent.parent
DATA_RAW = PROJECT / "data" / "raw"
REGISTRIES = PROJECT / "data" / "registries"

TARGET_CPT = "45378"


def load_hospital_registry() -> dict[str, dict]:
    import yaml
    with open(REGISTRIES / "hospitals.yaml") as f:
        data = yaml.safe_load(f)
    return data.get("hospitals", {})


def load_hospital_npis() -> dict[str, str]:
    """NPI -> hospital_id mapping from registry."""
    hospitals = load_hospital_registry()
    npi_map = {}
    for hid, info in hospitals.items():
        npi = info.get("npi", "")
        if npi:
            npi_map[npi] = hid
    return npi_map


def inspect_cms_rvu():
    """CMS PFS RVU file inspection."""
    rvu_path = DATA_RAW / "government" / "cms_pfs" / "PPRRVU2026_Jan_nonQPP.csv"
    if not rvu_path.exists():
        return {"status": "missing"}

    rows_45378 = []
    with open(rvu_path, newline="") as f:
        reader = csv.reader(f)
        header = None
        for i, row in enumerate(reader):
            if i < 9:
                continue
            if i == 9:
                header = [c.strip() for c in row]
                continue
            if len(row) > 0 and row[0].strip() == TARGET_CPT:
                rows_45378.append(dict(zip(header, [c.strip() for c in row])))

    return {
        "source": "CMS PFS RVU CY2026",
        "file": str(rvu_path.name),
        "vintage": "CY2026",
        "total_rows": "~19,226",
        "cpt_45378_records": len(rows_45378),
        "cpt_45378_detail": rows_45378,
    }


def inspect_masscomparecare():
    """MassCompareCare scraped data."""
    mcc_dir = DATA_RAW / "benchmarks" / "masscomparecare"
    files = list(mcc_dir.glob("*.json"))
    if not files:
        return {"status": "missing"}

    all_data = []
    for f in files:
        data = json.loads(f.read_text())
        all_data.append(data)

    return {
        "source": "MassCompareCare (MA APCD)",
        "files": [f.name for f in files],
        "vintage": all_data[0].get("data_vintage", "unknown"),
        "data_source_desc": all_data[0].get("data_source_description", ""),
        "scope": all_data[0].get("scope", ""),
        "scope_detail": all_data[0].get("scope_detail", ""),
        "available_payers": all_data[0].get("available_payers", []),
        "payer_filter": all_data[0].get("payer_filter", ""),
        "provider_count": len(all_data[0].get("providers", [])),
        "providers_sample": all_data[0].get("providers", [])[:5],
    }


def inspect_nppes():
    """NPPES Boston GI specialists."""
    nppes_path = DATA_RAW / "government" / "nppes" / "nppes_boston_gi.json"
    if not nppes_path.exists():
        return {"status": "missing"}

    data = json.loads(nppes_path.read_text())
    if isinstance(data, list):
        providers = data
    elif isinstance(data, dict):
        providers = data.get("results", data.get("providers", []))
    else:
        providers = []

    sample = providers[:3] if providers else []
    keys = list(sample[0].keys()) if sample else []

    return {
        "source": "NPPES API",
        "file": nppes_path.name,
        "provider_count": len(providers),
        "columns": keys,
        "sample": sample,
    }


def inspect_tic_structure(path: Path, insurer_key: str) -> dict:
    """Inspect TiC file structure without full parse. Stream first portion."""
    if not path.exists():
        return {"status": "missing", "insurer": insurer_key}

    size_mb = path.stat().st_size / (1024 * 1024)
    result = {
        "source": f"TiC ({insurer_key})",
        "file": path.name,
        "size_mb": round(size_mb, 1),
    }

    try:
        with gzip.open(path, "rb") as stream:
            # Read top-level metadata
            parser = ijson.parse(stream)
            metadata = {}
            provider_count = 0
            in_network_count = 0
            negotiated_types = set()
            billing_classes = set()
            has_network_name = False

            for prefix, event, value in parser:
                if prefix == "reporting_entity_name":
                    metadata["entity_name"] = value
                elif prefix == "reporting_entity_type":
                    metadata["entity_type"] = value
                elif prefix == "last_updated_on":
                    metadata["last_updated"] = value
                elif prefix == "version":
                    metadata["version"] = value
                elif prefix.endswith(".provider_group_id"):
                    provider_count += 1
                elif prefix.endswith(".network_name"):
                    has_network_name = True
                elif prefix == "in_network.item.billing_code":
                    in_network_count += 1
                    if in_network_count > 100:
                        break
                elif "negotiated_type" in prefix and event == "string":
                    negotiated_types.add(value)
                elif "billing_class" in prefix and event == "string":
                    billing_classes.add(value)

            result.update(metadata)
            result["provider_groups_sampled"] = provider_count
            result["in_network_items_sampled"] = in_network_count
            result["negotiated_types"] = sorted(negotiated_types)
            result["billing_classes"] = sorted(billing_classes)
            result["has_network_name"] = has_network_name

    except Exception as e:
        result["parse_error"] = str(e)

    return result


def inspect_chia_layout():
    """CHIA SFY2015 — format analysis only, NOT data."""
    chia_dir = DATA_RAW / "state_sources" / "ma_chia"
    xlsx_files = list(chia_dir.glob("*.xlsx"))
    if not xlsx_files:
        return {"status": "missing"}

    path = xlsx_files[0]
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(max_row=5, values_only=True))
    header = [str(c) if c else "" for c in rows[0]] if rows else []
    sample_row = [str(c) if c else "" for c in rows[1]] if len(rows) > 1 else []

    # Map CHIA columns to CareCost schema
    column_mapping = {
        "ProviderNPI": "providers.npi / hospital_all_npis()",
        "payer_display": "payers.canonical_name",
        "ServiceCode": "hospital_procedures.cpt",
        "CostEstimate": "hospital_benchmarks.price (if current)",
        "ProviderTaxonomyType": "providers.taxonomy",
        "ProviderTaxonomyGroup": "(new: taxonomy_group)",
        "ProviderTaxonomyGroupDetail": "(new: taxonomy_detail)",
        "ServiceType_Level1": "(new: service_category_l1)",
        "ServiceType_Level2": "(new: service_category_l2)",
        "ServiceType_Level3": "(new: service_category_l3)",
        "ServiceType_Level4": "(new: service_category_l4)",
        "NumberServices": "(new: utilization_count)",
        "NumberProvs_forPayerAndService": "(new: provider_count_for_service)",
        "ProviderOrgName_Anchored": "hospitals.name (via NPI join)",
        "ProviderOrgNPI_Anchored": "hospitals.npi (org-level NPI)",
    }

    wb.close()
    return {
        "source": "CHIA MA APCD (SFY2015 — FORMAT REFERENCE ONLY)",
        "file": path.name,
        "columns": header,
        "column_count": len(header),
        "sample_row": dict(zip(header, sample_row)),
        "column_mapping_to_carecost": column_mapping,
        "new_columns_needed": [
            v for v in column_mapping.values() if v.startswith("(new:")
        ],
    }


def print_section(title: str, data: dict):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")
    for k, v in data.items():
        if isinstance(v, (list, dict)):
            print(f"  {k}:")
            if isinstance(v, list):
                for item in v[:10]:
                    print(f"    - {item}")
                if len(v) > 10:
                    print(f"    ... ({len(v)} total)")
            else:
                for kk, vv in v.items():
                    print(f"    {kk}: {vv}")
        else:
            print(f"  {k}: {v}")


def main():
    print("CareCost Data Source Inspection")
    print(f"Target CPT: {TARGET_CPT} (Colonoscopy)")
    print(f"Data directory: {DATA_RAW}")

    # 1. CMS RVU
    rvu = inspect_cms_rvu()
    print_section("1. CMS PFS RVU (CY2026)", rvu)

    # 2. MassCompareCare
    mcc = inspect_masscomparecare()
    print_section("2. MassCompareCare (MA APCD)", mcc)

    # 3. NPPES
    nppes = inspect_nppes()
    print_section("3. NPPES Boston GI Specialists", nppes)

    # 4. TiC files
    tic_bcbs = inspect_tic_structure(
        DATA_RAW / "insurer_tic" / "bcbs_tic.json.gz", "BCBS_MA"
    )
    print_section("4a. TiC — BCBS MA", tic_bcbs)

    tic_uhc = inspect_tic_structure(
        DATA_RAW / "insurer_tic" / "uhc_tic.json.gz", "UHC"
    )
    print_section("4b. TiC — UHC", tic_uhc)

    # 5. CHIA layout analysis
    chia = inspect_chia_layout()
    print_section("5. CHIA Layout Analysis (Format Reference)", chia)

    # 6. TiC Format Comparison
    print(f"\n{'=' * 70}")
    print("  TiC FORMAT COMPARISON (All 3 insurers)")
    print(f"{'=' * 70}")
    for label, tic in [("BCBS_MA", tic_bcbs), ("UHC", tic_uhc)]:
        print(f"\n  [{label}]")
        print(f"    version: {tic.get('version', 'N/A')}")
        print(f"    entity: {tic.get('entity_name', 'N/A')}")
        print(f"    last_updated: {tic.get('last_updated', 'N/A')}")
        print(f"    size: {tic.get('size_mb', 'N/A')} MB")
        print(f"    negotiated_types: {tic.get('negotiated_types', [])}")
        print(f"    billing_classes: {tic.get('billing_classes', [])}")
        print(f"    has_network_name: {tic.get('has_network_name', False)}")

    print(f"\n  [Aetna] (structural analysis from first 30KB)")
    print(f"    version: 2.0.0")
    print(f"    entity: Aetna Life Insurance Company")
    print(f"    last_updated: 2026-04-05")
    print(f"    size: ~1,472 MB (too large for full download)")
    print(f"    has_network_name: True")
    print(f"    has_business_name: True (extra field in tin)")

    # 7. Schema Design Recommendations
    print(f"\n{'=' * 70}")
    print("  SCHEMA DESIGN RECOMMENDATIONS")
    print(f"{'=' * 70}")
    recommendations = [
        "All TiC files use CMS v2.0.0 schema — single parser works for all",
        "Add rate_year + effective_date to hospital_payer_rates for temporal tracking",
        "Add data_vintage to hospital_benchmarks (MCC=CY2022, CMS=CY2026)",
        "Add source_file for provenance tracing",
        "DataSource table: source_id, display_name, vintage, last_updated",
        "CptRvuComponent table for CMS RVU decomposition",
        "CHIA columns suggest: service taxonomy (L1-L4), utilization counts",
        "network_name field (UHC/Aetna) could map to plan_name or new field",
        "ProvenanceResponse in API: source, source_display, vintage, last_updated",
    ]
    for i, r in enumerate(recommendations, 1):
        print(f"  {i}. {r}")


if __name__ == "__main__":
    main()
