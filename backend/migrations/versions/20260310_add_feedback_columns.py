"""Add missing columns and tables for feedback loop system.

Fixes:
- clip_feedback: add rating, reason_tags columns (used by feedback_loop.py)
- clip_feedback: add UNIQUE constraint on (video_id, phase_index) for ON CONFLICT
- sales_confirmation: create table (used by feedback_loop.py)
- clip_edit_log: create table (used by feedback_loop.py)

Revision ID: 20260310_feedback_cols
Revises: 20260309_missing_cols
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260310_feedback_cols"
down_revision = "20260309_missing_cols"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add rating and reason_tags columns to clip_feedback
    op.add_column(
        "clip_feedback",
        sa.Column("rating", sa.String(20), nullable=True,
                  comment="Quick rating: good or bad"),
    )
    op.add_column(
        "clip_feedback",
        sa.Column("reason_tags", postgresql.JSONB(), nullable=True,
                  comment="Reason tags array: hook_weak, too_long, etc."),
    )

    # 2. Add UNIQUE constraint on (video_id, phase_index) for ON CONFLICT
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_clip_feedback_video_phase'
            ) THEN
                ALTER TABLE clip_feedback
                ADD CONSTRAINT uq_clip_feedback_video_phase
                UNIQUE (video_id, phase_index);
            END IF;
        END $$;
    """)

    # 3. Create sales_confirmation table
    op.execute("""
        CREATE TABLE IF NOT EXISTS sales_confirmation (
            id UUID PRIMARY KEY,
            video_id UUID NOT NULL,
            phase_index INTEGER NOT NULL,
            time_start FLOAT NOT NULL,
            time_end FLOAT NOT NULL,
            is_sales_moment BOOLEAN NOT NULL,
            clip_id UUID,
            confidence INTEGER,
            note TEXT,
            reviewer_name VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_sales_confirmation_video_phase UNIQUE (video_id, phase_index)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sales_confirmation_video_id
        ON sales_confirmation (video_id);
    """)

    # 4. Create clip_edit_log table
    op.execute("""
        CREATE TABLE IF NOT EXISTS clip_edit_log (
            id UUID PRIMARY KEY,
            clip_id UUID NOT NULL,
            video_id UUID NOT NULL,
            edit_type VARCHAR(50) NOT NULL,
            before_value JSONB,
            after_value JSONB,
            delta_seconds FLOAT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_clip_edit_log_video_id
        ON clip_edit_log (video_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_clip_edit_log_clip_id
        ON clip_edit_log (clip_id);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS clip_edit_log;")
    op.execute("DROP TABLE IF EXISTS sales_confirmation;")
    op.execute("""
        ALTER TABLE clip_feedback
        DROP CONSTRAINT IF EXISTS uq_clip_feedback_video_phase;
    """)
    op.drop_column("clip_feedback", "reason_tags")
    op.drop_column("clip_feedback", "rating")
