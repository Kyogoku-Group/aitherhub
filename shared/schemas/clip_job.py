"""
Clip Job State Management
==========================
Database operations for clip job lifecycle.
Used by Worker to update job state during processing.

State machine:
    pending → queued → downloading → processing → uploading → completed
                                                              ↓
                                                          failed → retrying → ...
                                                              ↓
                                                            dead
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from shared.schemas.video_status import ClipStatus


async def claim_clip_job(
    session,
    clip_id: str,
    worker_id: str,
) -> bool:
    """Claim a clip job for processing. Returns True if successfully claimed."""
    result = await session.execute(
        text("""
            UPDATE video_clips
            SET status = :status,
                worker_id = :worker_id,
                started_at = NOW(),
                heartbeat_at = NOW(),
                attempt_count = attempt_count + 1,
                updated_at = NOW()
            WHERE id = :clip_id
              AND status IN ('pending', 'queued', 'retrying')
            RETURNING id
        """),
        {
            "status": ClipStatus.DOWNLOADING,
            "worker_id": worker_id,
            "clip_id": clip_id,
        },
    )
    row = result.fetchone()
    return row is not None


async def update_clip_status(
    session,
    clip_id: str,
    status: str,
    clip_url: Optional[str] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None,
):
    """Update clip job status with optional metadata."""
    params = {"status": status, "clip_id": clip_id}
    set_clauses = ["status = :status", "updated_at = NOW()"]

    if clip_url is not None:
        set_clauses.append("clip_url = :clip_url")
        params["clip_url"] = clip_url

    if error_code is not None:
        set_clauses.append("last_error_code = :error_code")
        params["error_code"] = error_code

    if error_message is not None:
        set_clauses.append("last_error_message = :error_message")
        params["error_message"] = error_message[:2000] if error_message else None

    if duration_ms is not None:
        set_clauses.append("duration_ms = :duration_ms")
        params["duration_ms"] = duration_ms

    if status in (ClipStatus.COMPLETED, ClipStatus.FAILED, ClipStatus.DEAD):
        set_clauses.append("finished_at = NOW()")

    sql = f"UPDATE video_clips SET {', '.join(set_clauses)} WHERE id = :clip_id"
    await session.execute(text(sql), params)


async def heartbeat_clip_job(session, clip_id: str):
    """Update heartbeat timestamp for a running clip job."""
    await session.execute(
        text("""
            UPDATE video_clips
            SET heartbeat_at = NOW(), updated_at = NOW()
            WHERE id = :clip_id
        """),
        {"clip_id": clip_id},
    )


async def mark_clip_dead(
    session,
    clip_id: str,
    reason: str,
):
    """Mark a clip job as dead (no more retries)."""
    await update_clip_status(
        session,
        clip_id,
        status=ClipStatus.DEAD,
        error_code="DEAD_LETTER",
        error_message=reason,
    )


async def get_stale_clip_jobs(session, stale_seconds: int = 300):
    """Find clip jobs with stale heartbeats (potential stuck jobs)."""
    result = await session.execute(
        text("""
            SELECT id, video_id, worker_id, status, heartbeat_at, started_at, attempt_count
            FROM video_clips
            WHERE status IN ('downloading', 'processing', 'uploading')
              AND (
                  heartbeat_at IS NULL
                  OR heartbeat_at < NOW() - MAKE_INTERVAL(secs => :stale_seconds)
              )
            ORDER BY started_at ASC
        """),
        {"stale_seconds": stale_seconds},
    )
    return [dict(row._mapping) for row in result.fetchall()]


async def get_retryable_clip_jobs(session):
    """Find failed clip jobs that can be retried."""
    result = await session.execute(
        text("""
            SELECT id, video_id, attempt_count, max_attempts, last_error_code
            FROM video_clips
            WHERE status = 'failed'
              AND attempt_count < max_attempts
            ORDER BY updated_at ASC
        """),
    )
    return [dict(row._mapping) for row in result.fetchall()]
