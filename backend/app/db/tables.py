"""SQLAlchemy ORM tables for PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class Procedure(Base):
    __tablename__ = "procedures"

    bundle_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    cpt_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    tags: Mapped[str] = mapped_column(Text, nullable=False)
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


class HospitalRate(Base):
    __tablename__ = "hospital_rates"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    hospital_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hospital_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    neighborhood: Mapped[str] = mapped_column(Text, nullable=False, default="")
    system: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_completeness: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cpt: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    cpt_desc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    gross_charge: Mapped[float | None] = mapped_column(Float, nullable=True)
    discounted_cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    de_identified_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    de_identified_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per-payer negotiated rates
    bcbs_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bcbs_source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    bcbs_plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aetna_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    aetna_source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aetna_plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    harvard_pilgrim_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    hp_plan_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hp_source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    uhc_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    uhc_source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Cross-validation: TiC insurer-side
    bcbs_tic_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    bcbs_tic_billing_class: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Integrity metadata
    billing_class: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    setting: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rate_methodology: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Benchmarks
    turquoise_bundled_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    turquoise_quality_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    masscomparecare_total_paid: Mapped[float | None] = mapped_column(Float, nullable=True)
    # FAIR Health component breakdown
    fh_physician_in_network: Mapped[float | None] = mapped_column(Float, nullable=True)
    fh_anesthesia_in_network: Mapped[float | None] = mapped_column(Float, nullable=True)
    fh_facility_hosp_in_network: Mapped[float | None] = mapped_column(Float, nullable=True)
    fh_pathology_in_network: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)


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
Index("ix_hospital_rates_hospital_cpt", HospitalRate.hospital_id, HospitalRate.cpt)
