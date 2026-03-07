"""Add upload_event_log table and upload stage columns to videos

Creates upload_event_log table for pipeline observability and adds
upload_last_stage, upload_error_stage, upload_error_message columns
to videos table.

Revision ID: 20260308_upload_event_log
Revises: 20260307_clip_feedback
Create Date: 2026-03-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260308_upload_event_log"
down_revision = "20260307_clip_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create upload_event_log table ──
    op.create_table(
        "upload_event_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("video_id", sa.String(36), nullable=False),
        sa.Column("upload_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(50), nullable=False, comment="Pipeline stage: validate | db_record | sas_generate | queue_build | enqueue | cleanup"),
        sa.Column("status", sa.String(20), nullable=False, comment="ok | error | skipped"),
        sa.Column("duration_ms", sa.Integer(), nullable=True, comment="Time taken for this stage in milliseconds"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="Error details if status=error"),
        sa.Column("error_type", sa.String(100), nullable=True, comment="Exception class name or error category"),
        sa.Column("metadata_json", sa.JSON(), nullable=True, comment="Additional context (file size, upload_type, etc.)"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_upload_event_video", "upload_event_log", ["video_id"])
    op.create_index("idx_upload_event_user", "upload_event_log", ["user_id"])
    op.create_index("idx_upload_event_stage", "upload_event_log", ["stage", "status"])
    op.create_index("idx_upload_event_created", "upload_event_log", ["created_at"])

    # ── 2. Add upload stage columns to videos table ──
    op.add_column("videos", sa.Column("upload_last_stage", sa.String(50), nullable=True, comment="Last completed upload pipeline stage"))
    op.add_column("videos", sa.Column("upload_error_stage", sa.String(50), nullable=True, comment="Stage where upload failed (if any)"))
    op.add_column("videos", sa.Column("upload_error_message", sa.Text(), nullable=True, comment="Error message from failed stage"))


def downgrade() -> None:
    op.drop_column("videos", "upload_error_message")
    op.drop_column("videos", "upload_error_stage")
    op.drop_column("videos", "upload_last_stage")
    op.drop_index("idx_upload_event_created", table_name="upload_event_log")
    op.drop_index("idx_upload_event_stage", table_name="upload_event_log")
    op.drop_index("idx_upload_event_user", table_name="upload_event_log")
    op.drop_index("idx_upload_event_video", table_name="upload_event_log")
    op.drop_table("upload_event_log")
