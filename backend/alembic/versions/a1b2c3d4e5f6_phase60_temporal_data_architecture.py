"""phase60 temporal data architecture

Revision ID: a1b2c3d4e5f6
Revises: 382ff9c1b7ad
Create Date: 2026-05-02 21:00:00.000000

Adds temporal tracking, provenance, RVU decomposition, and data source registry.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '382ff9c1b7ad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New tables ---

    op.create_table('cpt_rvu_components',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('cpt', sa.String(length=32), nullable=False),
        sa.Column('modifier', sa.String(length=8), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('work_rvu', sa.Float(), nullable=True),
        sa.Column('facility_pe_rvu', sa.Float(), nullable=True),
        sa.Column('non_facility_pe_rvu', sa.Float(), nullable=True),
        sa.Column('malpractice_rvu', sa.Float(), nullable=True),
        sa.Column('facility_total_rvu', sa.Float(), nullable=True),
        sa.Column('non_facility_total_rvu', sa.Float(), nullable=True),
        sa.Column('conversion_factor', sa.Float(), nullable=True),
        sa.Column('global_surgery', sa.String(length=8), nullable=False, server_default=''),
        sa.Column('pfs_year', sa.Integer(), nullable=False),
        sa.Column('source_file', sa.Text(), nullable=False, server_default=''),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cpt', 'modifier', 'pfs_year', name='uq_cpt_rvu_natural_key'),
    )
    op.create_index('ix_cpt_rvu_components_cpt', 'cpt_rvu_components', ['cpt'], unique=False)

    op.create_table('data_sources',
        sa.Column('source_id', sa.String(length=64), nullable=False),
        sa.Column('source_type', sa.String(length=32), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('display_name', sa.Text(), nullable=False, server_default=''),
        sa.Column('legal_basis', sa.Text(), nullable=False, server_default=''),
        sa.Column('coverage_scope', sa.Text(), nullable=False, server_default=''),
        sa.Column('current_vintage', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=True),
        sa.Column('update_frequency', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('url', sa.Text(), nullable=False, server_default=''),
        sa.Column('state', sa.String(length=8), nullable=False, server_default=''),
        sa.PrimaryKeyConstraint('source_id'),
    )

    # --- Temporal columns on existing tables ---

    # hospitals: facility_type, is_curated
    op.add_column('hospitals', sa.Column('facility_type', sa.String(length=32), nullable=False, server_default='general_acute'))
    op.add_column('hospitals', sa.Column('is_curated', sa.Boolean(), nullable=False, server_default=sa.text('true')))

    # hospital_procedures: last_updated
    op.add_column('hospital_procedures', sa.Column('last_updated', sa.DateTime(timezone=True), nullable=True))

    # hospital_payer_rates: effective_date, rate_year
    op.add_column('hospital_payer_rates', sa.Column('effective_date', sa.String(length=32), nullable=False, server_default=''))
    op.add_column('hospital_payer_rates', sa.Column('rate_year', sa.Integer(), nullable=True))
    op.create_index('ix_hospital_payer_rates_rate_year', 'hospital_payer_rates', ['rate_year'], unique=False)

    # Drop old unique constraint and recreate with rate_year
    op.drop_constraint('uq_hospital_payer_rates_natural_key', 'hospital_payer_rates', type_='unique')
    op.create_unique_constraint(
        'uq_hospital_payer_rates_natural_key',
        'hospital_payer_rates',
        ['hospital_id', 'cpt', 'payer_id', 'source_origin', 'plan_name', 'rate_year'],
    )

    # hospital_benchmarks: source_file, effective_date, data_vintage
    op.add_column('hospital_benchmarks', sa.Column('source_file', sa.Text(), nullable=False, server_default=''))
    op.add_column('hospital_benchmarks', sa.Column('effective_date', sa.String(length=32), nullable=False, server_default=''))
    op.add_column('hospital_benchmarks', sa.Column('data_vintage', sa.String(length=32), nullable=False, server_default=''))


def downgrade() -> None:
    # hospital_benchmarks
    op.drop_column('hospital_benchmarks', 'data_vintage')
    op.drop_column('hospital_benchmarks', 'effective_date')
    op.drop_column('hospital_benchmarks', 'source_file')

    # hospital_payer_rates
    op.drop_constraint('uq_hospital_payer_rates_natural_key', 'hospital_payer_rates', type_='unique')
    op.create_unique_constraint(
        'uq_hospital_payer_rates_natural_key',
        'hospital_payer_rates',
        ['hospital_id', 'cpt', 'payer_id', 'source_origin', 'plan_name'],
    )
    op.drop_index('ix_hospital_payer_rates_rate_year', table_name='hospital_payer_rates')
    op.drop_column('hospital_payer_rates', 'rate_year')
    op.drop_column('hospital_payer_rates', 'effective_date')

    # hospital_procedures
    op.drop_column('hospital_procedures', 'last_updated')

    # hospitals
    op.drop_column('hospitals', 'is_curated')
    op.drop_column('hospitals', 'facility_type')

    # drop new tables
    op.drop_table('data_sources')
    op.drop_index('ix_cpt_rvu_components_cpt', table_name='cpt_rvu_components')
    op.drop_table('cpt_rvu_components')
