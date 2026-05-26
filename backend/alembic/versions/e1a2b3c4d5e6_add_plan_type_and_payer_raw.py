"""Add plan_type and payer_raw to hospital_payer_rates.

Revision ID: e1a2b3c4d5e6
Revises: d81483b732bf
Create Date: 2026-05-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "d81483b732bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hospital_payer_rates",
        sa.Column("plan_type", sa.String(32), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "hospital_payer_rates",
        sa.Column("payer_raw", sa.Text(), nullable=False, server_default=""),
    )
    op.create_check_constraint(
        "ck_hospital_payer_rates_plan_type",
        "hospital_payer_rates",
        "plan_type IN ('commercial', 'medicare', 'medicaid', 'unknown')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_hospital_payer_rates_plan_type", "hospital_payer_rates", type_="check")
    op.drop_column("hospital_payer_rates", "payer_raw")
    op.drop_column("hospital_payer_rates", "plan_type")
