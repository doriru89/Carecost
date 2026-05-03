"""fix rate_year null in unique constraint

NULL in unique constraint columns causes ON CONFLICT to never match
(PostgreSQL treats NULL != NULL). Backfill to 0 and set NOT NULL.

Revision ID: 17773a179d4d
Revises: a1b2c3d4e5f6
Create Date: 2026-05-02 21:22:28.548153

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '17773a179d4d'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE hospital_payer_rates SET rate_year = 0 WHERE rate_year IS NULL")
    op.alter_column(
        'hospital_payer_rates', 'rate_year',
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text('0'),
    )


def downgrade() -> None:
    op.alter_column(
        'hospital_payer_rates', 'rate_year',
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )
