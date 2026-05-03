"""purge_stale_seed_rows

Revision ID: 382ff9c1b7ad
Revises: 9c1014931eae
Create Date: 2026-05-02 20:00:07.845565

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '382ff9c1b7ad'
down_revision: Union[str, Sequence[str], None] = '9c1014931eae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM hospital_payer_rates WHERE source_file = ''"
    )


def downgrade() -> None:
    pass
