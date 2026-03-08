"""create clip_segments and video_scores tables for Intelligent Clip Editor v2

Revision ID: 20260308_clip_segments
Revises: lb20260308001
Create Date: 2026-03-08 22:00:00.000000

clip_segments: Segment-level AI scores (5-10s windows) for timeline heatmap
video_scores:  Video-level overall evaluation (viral, hook, sales, clipability)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260308_clip_segments"
down_revision = "lb20260308001"
branch_labels = None
depends_on = None


def upgrade():
    # ── clip_segments ─────────────────────────────────────────────────
    op.create_table(
        "clip_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_sec", sa.Float(), nullable=False),
        sa.Column("end_sec", sa.Float(), nullable=False),
        # Phase reference (nullable: segments may span phases)
        sa.Column("phase_index", sa.Integer(), nullable=True),
        # AI scores (0-100)
        sa.Column("viral_score", sa.Float(), nullable=True),
        sa.Column("hook_score", sa.Float(), nullable=True),
        sa.Column("sales_score", sa.Float(), nullable=True),
        sa.Column("comment_score", sa.Float(), nullable=True),
        sa.Column("retention_score", sa.Float(), nullable=True),
        sa.Column("speech_energy", sa.Float(), nullable=True),
        # Marker type: 'hook', 'sales_peak', 'comment_spike', 'speech_peak', 'product_mention'
        sa.Column("marker_type", sa.String(50), nullable=True),
        # Marker metadata (e.g., product name, comment text)
        sa.Column("marker_meta", postgresql.JSONB(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_clip_segments_video_id", "clip_segments", ["video_id"])
    op.create_index("ix_clip_segments_video_time", "clip_segments",
                    ["video_id", "start_sec", "end_sec"])
    op.create_index("ix_clip_segments_marker_type", "clip_segments",
                    ["video_id", "marker_type"])

    # ── video_scores ──────────────────────────────────────────────────
    op.create_table(
        "video_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False,
                  unique=True),
        # Overall scores (0-100)
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("viral_potential", sa.Float(), nullable=True),
        sa.Column("clipability_score", sa.Float(), nullable=True),
        sa.Column("sales_density", sa.Float(), nullable=True),
        sa.Column("hook_density", sa.Float(), nullable=True),
        sa.Column("reusability_score", sa.Float(), nullable=True),
        # Score breakdown JSON (detailed per-metric breakdown)
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=True),
        # Number of strong segments, clip candidates, etc.
        sa.Column("strong_segment_count", sa.Integer(), nullable=True),
        sa.Column("clip_candidate_count", sa.Integer(), nullable=True),
        sa.Column("best_hook_time", sa.Float(), nullable=True),
        sa.Column("best_sales_time", sa.Float(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_video_scores_video_id", "video_scores", ["video_id"])

    # ── segment_feedback (user feedback on timeline segments) ─────────
    op.create_table(
        "segment_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        # Time range (can be independent of segments)
        sa.Column("start_sec", sa.Float(), nullable=False),
        sa.Column("end_sec", sa.Float(), nullable=False),
        # Feedback type: 'good', 'weak', 'sold_well', 'skip', 'used'
        sa.Column("feedback_type", sa.String(30), nullable=False),
        # Label: 'sales_moment', 'comment_explosion', 'strong_hook',
        #        'clear_explanation', 'product_appeal', 'too_long', 'weak', 'dropout'
        sa.Column("label", sa.String(50), nullable=True),
        # Optional note
        sa.Column("note", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_segment_feedback_video_id", "segment_feedback",
                    ["video_id"])
    op.create_index("ix_segment_feedback_segment_id", "segment_feedback",
                    ["segment_id"])
    op.create_index("ix_segment_feedback_user_id", "segment_feedback",
                    ["user_id"])


def downgrade():
    op.drop_index("ix_segment_feedback_user_id", table_name="segment_feedback")
    op.drop_index("ix_segment_feedback_segment_id", table_name="segment_feedback")
    op.drop_index("ix_segment_feedback_video_id", table_name="segment_feedback")
    op.drop_table("segment_feedback")

    op.drop_index("ix_video_scores_video_id", table_name="video_scores")
    op.drop_table("video_scores")

    op.drop_index("ix_clip_segments_marker_type", table_name="clip_segments")
    op.drop_index("ix_clip_segments_video_time", table_name="clip_segments")
    op.drop_index("ix_clip_segments_video_id", table_name="clip_segments")
    op.drop_table("clip_segments")
