"""Add article_type column to section_232_materials for Note 16 compliance

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-11

Adds 'article_type' column to section_232_materials table to distinguish between:
- 'primary': Ch 72/76 raw materials → full value assessment, codes 9903.80.01/9903.85.03
- 'derivative': Ch 73 steel articles → full value assessment, codes 9903.81.89/9903.81.90
- 'content': Other chapters → content value only, codes 9903.81.91/9903.85.08

Per U.S. Note 16 to Chapter 99 and Presidential Proclamations 9980/10896:
- Primary and derivative articles: 232 duty on FULL entered value
- Content articles: 232 duty only on metal content value
- IEEPA Reciprocal: Primary/derivative exempt 100%, content exempt only metal portion

v11.0 Update (Jan 2026):
- Simplified migration: article_type now comes from CSV (data-driven)
- Removed hardcoded UPDATE statements - data populated by populate_tariff_tables.py
- CSV file section_232_hts_codes.csv contains article_type column
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Add article_type column with default 'content' (safest assumption)
    # v11.0: article_type values now come from CSV via populate_tariff_tables.py
    # No hardcoded UPDATE statements - data is data-driven from source CSV
    with op.batch_alter_table('section_232_materials', schema=None) as batch_op:
        batch_op.add_column(sa.Column('article_type', sa.String(16), nullable=False, server_default='content'))


def downgrade():
    with op.batch_alter_table('section_232_materials', schema=None) as batch_op:
        batch_op.drop_column('article_type')
