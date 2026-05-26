"""SQLAlchemy ORM tables for PostgreSQL.

Schema v2: temporal tracking, provenance, RVU decomposition, data source registry.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Provider(Base):
    __tablename__ = "providers"

    npi: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    zip: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str | None] = mapped_column(String(8), nullable=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    taxonomy: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    specialties: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    hospital: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hospital_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("hospitals.hospital_id"), nullable=True
    )


class Procedure(Base):
    __tablename__ = "procedures"

    bundle_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    specialty: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cpt_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=[])
    source: Mapped[str] = mapped_column(Text, nullable=False)


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(
        String(20), ForeignKey("providers.npi", ondelete="CASCADE"), nullable=False, index=True
    )
    bundle_id: Mapped[str] = mapped_column(String(128), nullable=False)
    min_rate_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    max_rate_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    payer: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    effective_date: Mapped[str] = mapped_column(String(32), nullable=False)
    mvp_hospital_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "bundle_id",
            "payer",
            "source",
            "effective_date",
            name="uq_prices_natural_key",
        ),
    )


class Insurer(Base):
    __tablename__ = "insurers"

    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    carrier: Mapped[str] = mapped_column(Text, nullable=False)
    deductible_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    oop_max_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    coinsurance_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    copay_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class Hospital(Base):
    __tablename__ = "hospitals"

    hospital_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    system_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String(8), nullable=False)
    metro_area: Mapped[str] = mapped_column(String(64), nullable=False)
    neighborhood: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    npi: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    facility_type: Mapped[str] = mapped_column(String(32), nullable=False, default="general_acute")
    is_curated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Payer(Base):
    __tablename__ = "payers"

    payer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_brand: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    payer_type: Mapped[str] = mapped_column(String(32), nullable=False, default="commercial")
    operating_states: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=[])
    tic_portal: Mapped[str] = mapped_column(Text, nullable=False, default="")


class HospitalProcedure(Base):
    __tablename__ = "hospital_procedures"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cpt: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    cpt_desc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    gross_charge: Mapped[float | None] = mapped_column(Float, nullable=True)
    discounted_cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    de_identified_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    de_identified_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    billing_class: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    setting: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rate_methodology: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_completeness: Mapped[str] = mapped_column(Text, nullable=False, default="")
    compliance_score: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    price_granularity: Mapped[str] = mapped_column(String(32), nullable=False, default="itemized")
    null_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="etl")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="mrf")
    rate_quality: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("hospital_id", "cpt", name="uq_hospital_procedures_hid_cpt"),
    )


class HospitalPayerRate(Base):
    __tablename__ = "hospital_payer_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hospital_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cpt: Mapped[str] = mapped_column(String(32), nullable=False)
    payer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    negotiated_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    plan_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_origin: Mapped[str] = mapped_column(String(32), nullable=False, default="mrf")
    billing_class: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price_source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    setting: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_file: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rate_methodology: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    effective_date: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    rate_year: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    payer_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint(
            "hospital_id",
            "cpt",
            "payer_id",
            "source_origin",
            "plan_name",
            "rate_year",
            name="uq_hospital_payer_rates_natural_key",
        ),
        CheckConstraint(
            "rate_methodology IN ('negotiated', 'derived', 'fee schedule', 'percentage', "
            "'per diem', 'case rate', 'capitation', 'other', '')",
            name="ck_hospital_payer_rates_methodology",
        ),
        CheckConstraint(
            "plan_type IN ('commercial', 'medicare', 'medicaid', 'unknown')",
            name="ck_hospital_payer_rates_plan_type",
        ),
    )


class HospitalBenchmark(Base):
    __tablename__ = "hospital_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hospital_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cpt: Mapped[str] = mapped_column(String(32), nullable=False)
    benchmark_source: Mapped[str] = mapped_column(String(64), nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False, default="total")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_file: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effective_date: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    data_vintage: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    __table_args__ = (
        UniqueConstraint(
            "hospital_id",
            "cpt",
            "benchmark_source",
            "component",
            name="uq_hospital_benchmarks_natural_key",
        ),
    )


class CptRvuComponent(Base):
    __tablename__ = "cpt_rvu_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cpt: Mapped[str] = mapped_column(String(32), nullable=False)
    modifier: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    work_rvu: Mapped[float | None] = mapped_column(Float, nullable=True)
    facility_pe_rvu: Mapped[float | None] = mapped_column(Float, nullable=True)
    non_facility_pe_rvu: Mapped[float | None] = mapped_column(Float, nullable=True)
    malpractice_rvu: Mapped[float | None] = mapped_column(Float, nullable=True)
    facility_total_rvu: Mapped[float | None] = mapped_column(Float, nullable=True)
    non_facility_total_rvu: Mapped[float | None] = mapped_column(Float, nullable=True)
    conversion_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    global_surgery: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    pfs_year: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("cpt", "modifier", "pfs_year", name="uq_cpt_rvu_natural_key"),
    )


class DataSource(Base):
    __tablename__ = "data_sources"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    legal_basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    coverage_scope: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_vintage: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    update_frequency: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[str] = mapped_column(String(8), nullable=False, default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    picture: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    user_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    insurance_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index("ix_providers_zip", Provider.zip)
Index("ix_providers_specialties_gin", Provider.specialties, postgresql_using="gin")
Index("ix_prices_provider_bundle_payer", Price.provider_id, Price.bundle_id, Price.payer)
Index("ix_hospital_procedures_hid_cpt", HospitalProcedure.hospital_id, HospitalProcedure.cpt)
Index(
    "ix_hospital_payer_rates_hid_cpt_payer",
    HospitalPayerRate.hospital_id,
    HospitalPayerRate.cpt,
    HospitalPayerRate.payer_id,
)
Index("ix_hospital_benchmarks_hid_cpt", HospitalBenchmark.hospital_id, HospitalBenchmark.cpt)
Index("ix_hospitals_metro_area", Hospital.metro_area)
Index("ix_hospitals_state", Hospital.state)
Index("ix_procedures_cpt_codes_gin", Procedure.cpt_codes, postgresql_using="gin")
Index("ix_cpt_rvu_components_cpt", CptRvuComponent.cpt)
Index("ix_hospital_payer_rates_rate_year", HospitalPayerRate.rate_year)
