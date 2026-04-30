"""Shared dataclasses for the ETL pipeline.

All monetary fields are float | None, unit is USD dollars.
Rounded to 2 decimal places at CSV write time by csv_builder.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RawMrfRecord:
    """One row extracted from a hospital MRF file, pre-normalization."""

    hospital_name: str
    cpt: str
    cpt_desc: str
    description: str
    payer_raw: str
    plan: str
    setting: str
    gross: float | None
    cash: float | None
    negotiated_dollar: float | None
    estimated_amount: float | None
    de_id_min: float | None
    de_id_max: float | None
    billing_class: str
    source_file: str
    mrf_format: str


@dataclass(frozen=True)
class RawTicRecord:
    """One matched rate from an insurer TiC file."""

    hospital_name: str
    matched_npi: str
    cpt: str
    cpt_desc: str
    negotiated_rate: float
    negotiated_type: str
    billing_class: str
    setting: str
    plan: str
    insurer_key: str
    source_file: str


@dataclass
class NormalizedRecord:
    """Hospital and payer resolved to registry IDs."""

    hospital_id: str
    cpt: str
    cpt_desc: str
    description: str
    payer_id: str | None
    payer_raw: str
    plan: str
    setting: str
    gross: float | None
    cash: float | None
    negotiated_dollar: float | None
    estimated_amount: float | None
    de_id_min: float | None
    de_id_max: float | None
    billing_class: str
    source_file: str
    source_origin: str
    mrf_format: str = ""


@dataclass
class QualifiedRecord(NormalizedRecord):
    """Enriched with provenance metadata."""

    source_type: str = "mrf"
    rate_quality: str = "unknown"
    price_source: str = ""
    rate_methodology: str = ""
    price_granularity: str = "itemized"


@dataclass
class ProcedureRecord:
    """Base facts for one (hospital_id, cpt), payer-independent."""

    hospital_id: str
    cpt: str
    cpt_desc: str
    gross_charge: float | None
    discounted_cash: float | None
    de_identified_min: float | None
    de_identified_max: float | None
    billing_class: str = "unknown"
    setting: str = ""
    rate_methodology: str = ""
    data_completeness: str = ""
    compliance_score: str = "unknown"
    price_granularity: str = "itemized"
    null_reason: str | None = None
    source_type: str = "mrf"
    rate_quality: str = "unknown"


@dataclass
class PayerRateRecord:
    """One negotiated rate for a (hospital, CPT, payer, source_origin) combination."""

    hospital_id: str
    cpt: str
    payer_id: str
    negotiated_rate: float | None
    plan_name: str = ""
    source: str = ""
    source_origin: str = "mrf"
    billing_class: str = ""
    price_source: str = ""


@dataclass
class BenchmarkRecord:
    """One benchmark data point for a (hospital, CPT, source, component)."""

    hospital_id: str
    cpt: str
    benchmark_source: str
    component: str = "total"
    price: float | None = None
    quality_rating: float | None = None


@dataclass
class MergeResult:
    """Output of the merger — 3 normalized record sets."""

    procedures: list[ProcedureRecord] = field(default_factory=list)
    payer_rates: list[PayerRateRecord] = field(default_factory=list)
    benchmarks: list[BenchmarkRecord] = field(default_factory=list)


# DEPRECATED — used only by legacy csv_import path (build_legacy_wide_csv).
@dataclass
class MergedRecord:
    """One row per (hospital_id, cpt) with all payer rates + benchmarks."""

    hospital_id: str
    hospital_name: str
    neighborhood: str
    system: str
    data_completeness: str
    cpt: str
    cpt_desc: str
    gross_charge: float | None
    discounted_cash: float | None
    de_identified_min: float | None
    de_identified_max: float | None
    bcbs_price: float | None = None
    bcbs_source: str = ""
    bcbs_plan: str = ""
    aetna_price: float | None = None
    aetna_source: str = ""
    aetna_plan: str = ""
    harvard_pilgrim_price: float | None = None
    hp_plan_name: str = ""
    hp_source: str = ""
    uhc_price: float | None = None
    uhc_source: str = ""
    bcbs_tic_rate: float | None = None
    bcbs_tic_billing_class: str = ""
    billing_class: str = "unknown"
    setting: str = ""
    rate_methodology: str = ""
    turquoise_bundled_price: float | None = None
    turquoise_quality_rating: float | None = None
    masscomparecare_total_paid: float | None = None
    fh_physician_in_network: float | None = None
    fh_physician_oon: float | None = None
    fh_anesthesia_in_network: float | None = None
    fh_facility_hosp_in_network: float | None = None
    fh_facility_asc_in_network: float | None = None
    fh_pathology_in_network: float | None = None
    price_granularity: str = "itemized"
    compliance_score: str = "unknown"
    null_reason: str | None = None
    source_type: str = "mrf"
    rate_quality: str = "unknown"


@dataclass(frozen=True)
class MrfFileSpec:
    """Describes one MRF file for extraction."""

    file_path: str
    hospital_id: str
    hospital_name: str
    mrf_format: str


@dataclass
class HospitalCoverage:
    """Per-hospital data coverage metadata for NULL reasoning."""

    hospital_id: str
    data_sources: list[str] = field(default_factory=list)
    payers_covered: list[str] = field(default_factory=list)
    price_granularity: str = "itemized"
    null_reason: str = "not_disclosed"
    compliance_score: str = "unknown"


@dataclass
class ValidationReport:
    """Output of data_validator.validate_etl_output()."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cross_validation: dict = field(default_factory=dict)


@dataclass
class EtlResult:
    """Summary of a complete ETL pipeline run."""

    specialty: str
    mrf_records_extracted: int
    tic_records_extracted: int
    records_after_normalization: int
    merged_rows: int
    csv_rows_written: int
    hospitals_found: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation_report: ValidationReport | None = None
    source_files: dict[str, str] = field(default_factory=dict)
    run_timestamp: str = ""
