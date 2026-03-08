"""add live_analysis_jobs table for LiveBoost Companion App

Revision ID: lb20260308001
Revises: (standalone – apply after latest head)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "lb20260308001"
down_revision = None  # standalone migration; run after current head
branch_labels = ("liveboost",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_analysis_jobs",
        # PK
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # Relations
        sa.Column("video_id", sa.String(255), nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        # Source
        sa.Column("stream_source", sa.String(50), server_default="tiktok_live", nullable=False),
        # Status
        sa.Column("status", sa.String(50), server_default="pending", nullable=False, index=True),
        sa.Column("current_step", sa.String(100), nullable=True),
        sa.Column("progress", sa.Float, nullable=True, server_default="0"),
        # Chunk tracking
        sa.Column("total_chunks", sa.Integer, nullable=True),
        sa.Column("assembled_blob_url", sa.Text, nullable=True),
        # Timing
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # Results
        sa.Column("results", sa.JSON, nullable=True),
        # Error
        sa.Column("error_message", sa.Text, nullable=True),
        # Queue evidence
        sa.Column("queue_message_id", sa.String(255), nullable=True),
        sa.Column("queue_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("live_analysis_jobs")
