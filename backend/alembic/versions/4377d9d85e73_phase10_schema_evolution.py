"""phase10_schema_evolution

Revision ID: 4377d9d85e73
Revises: d81483b732bf
Create Date: 2026-05-02 00:40:38.023039

Phase 10 schema evolution:
 1. Create hospitals + payers dimension tables (populated from YAML)
 2. Evolve procedures (add specialty, description; tags Text→TEXT[])
 3. Populate procedures from cpt_bundles.yaml
 4. Evolve hospital_payer_rates (add columns, fix unique constraint, CHECK)
 5. Add FKs between tables
 6. Add indexes
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

import yaml
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "4377d9d85e73"
down_revision: Union[str, Sequence[str], None] = "d81483b732bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Path to data registries (relative to backend/)
_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "registries"


def _load_yaml(name: str) -> dict:
    return yaml.safe_load((_DATA_DIR / name).read_text())


def upgrade() -> None:
    """Upgrade schema."""
    # ── 1. Create hospitals table ──
    op.create_table(
        "hospitals",
        sa.Column("hospital_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("system_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=8), nullable=False),
        sa.Column("metro_area", sa.String(length=64), nullable=False),
        sa.Column("neighborhood", sa.Text(), nullable=False, server_default=""),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("npi", sa.String(length=20), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("hospital_id"),
    )
    op.create_index("ix_hospitals_metro_area", "hospitals", ["metro_area"])
    op.create_index("ix_hospitals_state", "hospitals", ["state"])

    # Populate hospitals from YAML
    hospitals_data = _load_yaml("hospitals.yaml")["hospitals"]
    hospitals_table = sa.table(
        "hospitals",
        sa.column("hospital_id", sa.String),
        sa.column("name", sa.Text),
        sa.column("system_name", sa.Text),
        sa.column("state", sa.String),
        sa.column("metro_area", sa.String),
        sa.column("neighborhood", sa.Text),
        sa.column("lat", sa.Float),
        sa.column("lng", sa.Float),
        sa.column("npi", sa.String),
    )
    rows = []
    for hid, h in hospitals_data.items():
        rows.append(
            {
                "hospital_id": hid,
                "name": h["name"],
                "system_name": h.get("system", ""),
                "state": h["state"],
                "metro_area": h["metro_area"],
                "neighborhood": h.get("neighborhood", ""),
                "lat": h.get("lat"),
                "lng": h.get("lng"),
                "npi": h.get("npi", ""),
            }
        )
    op.bulk_insert(hospitals_table, rows)

    # ── 2. Create payers table ──
    op.create_table(
        "payers",
        sa.Column("payer_id", sa.String(length=32), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("parent_brand", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("payer_type", sa.String(length=32), nullable=False, server_default="commercial"),
        sa.Column(
            "operating_states", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("tic_portal", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("payer_id"),
    )

    # Populate payers from YAML
    payers_data = _load_yaml("payers.yaml")["payers"]
    payers_table = sa.table(
        "payers",
        sa.column("payer_id", sa.String),
        sa.column("canonical_name", sa.Text),
        sa.column("parent_brand", sa.String),
        sa.column("payer_type", sa.String),
        sa.column("operating_states", postgresql.ARRAY(sa.Text)),
        sa.column("tic_portal", sa.Text),
    )
    payer_rows = []
    for pid, p in payers_data.items():
        payer_rows.append(
            {
                "payer_id": pid,
                "canonical_name": p["label"],
                "parent_brand": p.get("parent_brand", ""),
                "payer_type": "commercial",
                "operating_states": p.get("operating_states", []),
                "tic_portal": p.get("tic_portal", ""),
            }
        )
    op.bulk_insert(payers_table, payer_rows)

    # ── 3. Evolve procedures table ──
    # Add specialty and description columns
    op.add_column(
        "procedures",
        sa.Column("specialty", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "procedures", sa.Column("description", sa.Text(), nullable=False, server_default="")
    )

    # Change tags from Text to TEXT[] (ARRAY)
    op.execute("ALTER TABLE procedures ALTER COLUMN tags TYPE TEXT[] USING ARRAY[tags]")

    # Set default for tags to empty array
    op.execute("ALTER TABLE procedures ALTER COLUMN tags SET DEFAULT '{}'")

    # Add GIN index on cpt_codes
    op.create_index(
        "ix_procedures_cpt_codes_gin", "procedures", ["cpt_codes"], postgresql_using="gin"
    )

    # Populate procedures from cpt_bundles.yaml (upsert — existing rows get updated)
    bundles_data = _load_yaml("cpt_bundles.yaml")["bundles"]
    conn = op.get_bind()
    for bid, b in bundles_data.items():
        cpt_val = b["cpt"]
        tags = b.get("tags", [])
        conn.execute(
            sa.text(
                "INSERT INTO procedures (bundle_id, label, specialty, description, cpt_codes, tags, source) "
                "VALUES (:bid, :label, :specialty, :description, ARRAY[:cpt]::TEXT[], CAST(:tags AS TEXT[]), :source) "
                "ON CONFLICT (bundle_id) DO UPDATE SET "
                "specialty = EXCLUDED.specialty, description = EXCLUDED.description, "
                "tags = EXCLUDED.tags"
            ),
            {
                "bid": bid,
                "label": b["label"],
                "specialty": b.get("specialty", ""),
                "description": b.get("description", ""),
                "cpt": cpt_val,
                "tags": "{" + ",".join(tags) + "}",
                "source": "cpt_bundles.yaml",
            },
        )

    # ── 4. Evolve hospital_payer_rates ──
    # Add new columns with server_default (existing rows get default)
    op.add_column(
        "hospital_payer_rates",
        sa.Column("setting", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "hospital_payer_rates",
        sa.Column("source_file", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "hospital_payer_rates",
        sa.Column("rate_methodology", sa.String(length=32), nullable=False, server_default=""),
    )

    # Backfill plan_name where NULL → '' (F1 safety)
    op.execute("UPDATE hospital_payer_rates SET plan_name = '' WHERE plan_name IS NULL")

    # Drop old unique constraint, create new one with plan_name
    op.drop_constraint(
        "uq_hospital_payer_rates_natural_key", "hospital_payer_rates", type_="unique"
    )
    op.create_unique_constraint(
        "uq_hospital_payer_rates_natural_key",
        "hospital_payer_rates",
        ["hospital_id", "cpt", "payer_id", "source_origin", "plan_name"],
    )

    # CHECK constraint on rate_methodology (CMS MRF values use spaces)
    op.create_check_constraint(
        "ck_hospital_payer_rates_methodology",
        "hospital_payer_rates",
        "rate_methodology IN ('negotiated', 'derived', 'fee schedule', 'percentage', "
        "'per diem', 'case rate', 'capitation', 'other', '')",
    )

    # ── 5. Add FKs ──
    op.create_foreign_key(
        "fk_hospital_payer_rates_hospital_id",
        "hospital_payer_rates",
        "hospitals",
        ["hospital_id"],
        ["hospital_id"],
    )
    op.create_foreign_key(
        "fk_hospital_payer_rates_payer_id",
        "hospital_payer_rates",
        "payers",
        ["payer_id"],
        ["payer_id"],
    )
    op.create_foreign_key(
        "fk_hospital_procedures_hospital_id",
        "hospital_procedures",
        "hospitals",
        ["hospital_id"],
        ["hospital_id"],
    )
    op.create_foreign_key(
        "fk_hospital_benchmarks_hospital_id",
        "hospital_benchmarks",
        "hospitals",
        ["hospital_id"],
        ["hospital_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop FKs
    op.drop_constraint(
        "fk_hospital_benchmarks_hospital_id", "hospital_benchmarks", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_hospital_procedures_hospital_id", "hospital_procedures", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_hospital_payer_rates_payer_id", "hospital_payer_rates", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_hospital_payer_rates_hospital_id", "hospital_payer_rates", type_="foreignkey"
    )

    # Revert hospital_payer_rates
    op.drop_constraint("ck_hospital_payer_rates_methodology", "hospital_payer_rates", type_="check")
    op.drop_constraint(
        "uq_hospital_payer_rates_natural_key", "hospital_payer_rates", type_="unique"
    )
    op.create_unique_constraint(
        "uq_hospital_payer_rates_natural_key",
        "hospital_payer_rates",
        ["hospital_id", "cpt", "payer_id", "source_origin"],
    )
    op.drop_column("hospital_payer_rates", "rate_methodology")
    op.drop_column("hospital_payer_rates", "source_file")
    op.drop_column("hospital_payer_rates", "setting")

    # Revert procedures
    op.drop_index("ix_procedures_cpt_codes_gin", table_name="procedures", postgresql_using="gin")
    op.execute("ALTER TABLE procedures ALTER COLUMN tags TYPE TEXT USING tags[1]")
    op.drop_column("procedures", "description")
    op.drop_column("procedures", "specialty")

    # Drop dimension tables
    op.drop_table("payers")
    op.drop_index("ix_hospitals_state", table_name="hospitals")
    op.drop_index("ix_hospitals_metro_area", table_name="hospitals")
    op.drop_table("hospitals")
