# app/models/orm/live_analysis_job.py
"""
LiveAnalysisJob – tracks the lifecycle of a live-stream analysis job
triggered by the LiveBoost Companion App.

Lifecycle:
  pending → assembling → audio_extraction → speech_to_text
  → ocr_processing → sales_detection → clip_generation → completed
  (any step may transition to 'failed')
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer,
    String,
    Text,
    Float,
    DateTime,
    JSON,
    ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.orm.base import Base, UUIDMixin, TimestampMixin


class LiveAnalysisJob(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "live_analysis_jobs"

    # ── Relations ──────────────────────────────────────────────
    video_id: Mapped[str] = mapped_column(
        String(255), index=True, nullable=False,
        comment="Logical video ID (may map to multiple chunks)",
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False,
    )

    # ── Source ─────────────────────────────────────────────────
    stream_source: Mapped[str] = mapped_column(
        String(50), default="tiktok_live", server_default="tiktok_live",
        comment="Origin platform: tiktok_live | instagram_live | etc.",
    )

    # ── Status ─────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(50), default="pending", server_default="pending",
        index=True,
        comment="Current pipeline step",
    )
    current_step: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="Human-readable current processing step",
    )
    progress: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0,
        comment="Overall progress 0.0 – 1.0",
    )

    # ── Chunk tracking ─────────────────────────────────────────
    total_chunks: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Total number of uploaded chunks",
    )
    assembled_blob_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Blob URL of the assembled full video",
    )

    # ── Timing ─────────────────────────────────────────────────
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # ── Results (JSON) ─────────────────────────────────────────
    results: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True,
        comment="Final analysis output: top_sales_moments, hooks, clips",
    )

    # ── Error ──────────────────────────────────────────────────
    error_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )

    # ── Queue evidence ─────────────────────────────────────────
    queue_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
    )
    queue_enqueued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
