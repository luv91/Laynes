"""Add role column to section_301_rates for exclusion precedence

Revision ID: a1b2c3d4e5f6
Revises: 5f4dff226bfa
Create Date: 2026-01-11

Adds 'role' column to section_301_rates table to distinguish between:
- 'impose' (default): Codes that add duty (e.g., 9903.88.03 for List 3)
- 'exclude': Codes that remove duty via USTR exclusion (e.g., 9903.88.69)

Per CBP guidance, exclusions take precedence over impose codes.
When filing an exclusion code, do NOT file the base duty code.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '5f4dff226bfa'
branch_labels = None
depends_on = None


def upgrade():
    # Add role column with default 'impose'
    with op.batch_alter_table('section_301_rates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(16), nullable=False, server_default='impose'))

    # Mark known exclusion codes
    # 9903.88.69 and 9903.88.70 are USTR exclusion extension codes
    op.execute("""
        UPDATE section_301_rates
        SET role = 'exclude'
        WHERE chapter_99_code IN ('9903.88.69', '9903.88.70')
    """)


def downgrade():
    with op.batch_alter_table('section_301_rates', schema=None) as batch_op:
        batch_op.drop_column('role')
