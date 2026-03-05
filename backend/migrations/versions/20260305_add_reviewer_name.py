"""add reviewer_name column to video_phases

Revision ID: 20260305_reviewer_name
Revises: 20260305_enqueue_evidence
Create Date: 2026-03-05
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260305_reviewer_name"
down_revision = "20260305_enqueue_evidence"
branch_labels = None
depends_on = None


def upgrade():
    # Add reviewer_name column (free text, nullable)
    # Stores the name of the person who rated/tagged this phase
    # Saved in browser localStorage, not tied to user account
    op.add_column(
        'video_phases',
        sa.Column('reviewer_name', sa.String(100), nullable=True)
    )


def downgrade():
    op.drop_column('video_phases', 'reviewer_name')
