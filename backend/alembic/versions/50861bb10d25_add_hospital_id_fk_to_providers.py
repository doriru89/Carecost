"""add_hospital_id_fk_to_providers

Revision ID: 50861bb10d25
Revises: 4377d9d85e73
Create Date: 2026-05-02 14:50:14.667135

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50861bb10d25'
down_revision: Union[str, Sequence[str], None] = '4377d9d85e73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('providers', sa.Column('hospital_id', sa.String(length=64), nullable=True))
    op.execute(
        "UPDATE providers p SET hospital_id = h.hospital_id "
        "FROM hospitals h WHERE p.hospital = h.name"
    )
    op.create_foreign_key(
        'fk_providers_hospital_id', 'providers', 'hospitals',
        ['hospital_id'], ['hospital_id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_providers_hospital_id', 'providers', type_='foreignkey')
    op.drop_column('providers', 'hospital_id')
