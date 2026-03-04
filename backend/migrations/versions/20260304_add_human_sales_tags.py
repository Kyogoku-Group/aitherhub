"""add human_sales_tags to video_phases

Revision ID: 20260304_human_tags
Revises: 20260304_sales_tags
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa

revision = '20260304_human_tags'
down_revision = '20260304_sales_tags'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('video_phases', sa.Column('human_sales_tags', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('video_phases', 'human_sales_tags')
