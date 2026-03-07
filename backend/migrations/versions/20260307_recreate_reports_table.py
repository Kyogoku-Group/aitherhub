"""Recreate reports table for Live Report v1

Revision ID: 20260307_recreate_reports
Revises: 20260307_ext_events
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260307_recreate_reports"
down_revision = "20260307_ext_events"
branch_labels = None
depends_on = None


def upgrade():
    # Recreate the reports table (was dropped in 20260201)
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("video_id", sa.UUID(), nullable=False),
        sa.Column("report_content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_video_id", "reports", ["video_id"])


def downgrade():
    op.drop_index("ix_reports_video_id", table_name="reports")
    op.drop_table("reports")
