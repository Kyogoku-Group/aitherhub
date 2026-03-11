"""
Live Analysis endpoints for the LiveBoost Companion App.

These endpoints handle the lifecycle of live-stream analysis jobs:
  - Start analysis after chunk upload completion
  - Poll analysis status
  - Generate per-chunk signed upload URLs

╔══════════════════════════════════════════════════════════════════╗
║  Routes:                                                        ║
║    POST /api/v1/live-analysis/start                              ║
║    GET  /api/v1/live-analysis/status/{video_id}                  ║
║    POST /api/v1/live-analysis/generate-chunk-upload-url          ║
╚══════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text
from loguru import logger

from app.core.db import get_db
from app.core.dependencies import get_current_user
from app.models.orm.live_analysis_job import LiveAnalysisJob
from app.models.orm.video import Video
from app.schemas.live_analysis_schema import (
    LiveAnalysisStartRequest,
    LiveAnalysisStartResponse,
    LiveAnalysisStatusResponse,
    AnalysisResults,
    GenerateChunkUploadURLRequest,
    GenerateChunkUploadURLResponse,
)
from app.services.storage_service import generate_upload_sas
from app.services.queue_service import enqueue_job


router = APIRouter(
    prefix="/live-analysis",
    tags=["live-analysis"],
)


# ──────────────────────────────────────────────
# 0. Migrate (one-time table creation)
# ──────────────────────────────────────────────
@router.post("/migrate")
async def migrate_tables():
    """
    One-time endpoint to create the live_analysis_jobs table.
    Safe to call multiple times (CREATE IF NOT EXISTS).
    """
    try:
        from app.core.db import engine

        async with engine.begin() as conn:
            await conn.run_sync(
                LiveAnalysisJob.__table__.create,
                checkfirst=True,
            )
        return {"status": "ok", "message": "live_analysis_jobs table verified/created successfully"}
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise HTTPException(status_code=500, detail=f"Migration failed: {str(e)}")


# ──────────────────────────────────────────────
# Helper: Ensure videos table record exists
# ──────────────────────────────────────────────
async def _ensure_video_record(
    db: AsyncSession,
    video_id: str,
    user_id: int,
    status_value: str = "pending",
) -> None:
    """
    BUILD 28: Ensure a corresponding record exists in the `videos` table
    so that LiveBoost sessions appear in AitherHub's History view.

    The History API (`/videos/user/{id}/with-clips`) queries the `videos`
    table, so LiveBoost sessions must have a record there to be visible.

    Uses INSERT ... ON DUPLICATE KEY UPDATE to be idempotent.
    """
    try:
        # Check if record already exists
        result = await db.execute(
            select(Video).where(Video.id == uuid_module.UUID(video_id))
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update status if it's being retried (failed → pending)
            if existing.status == "ERROR" and status_value == "pending":
                existing.status = "uploaded"
                existing.step_progress = 0
                await db.flush()
                logger.info(
                    f"[live-analysis] Reset videos record for retry: "
                    f"video={video_id} status=uploaded"
                )
        else:
            # Create new record
            video = Video(
                id=uuid_module.UUID(video_id),
                user_id=user_id,
                original_filename=f"LiveBoost_{datetime.now(timezone.utc).strftime('%m%d_%H%M')}",
                status=status_value,
                upload_type="live_boost",
                step_progress=0,
            )
            db.add(video)
            await db.flush()
            logger.info(
                f"[live-analysis] Created videos record: "
                f"video={video_id} user={user_id} upload_type=live_boost"
            )
    except Exception as e:
        logger.warning(f"[live-analysis] Failed to ensure video record: {e}")
        # Non-critical — don't block the analysis pipeline


# ──────────────────────────────────────────────
# 1. Start Analysis
# ──────────────────────────────────────────────
@router.post("/start", response_model=LiveAnalysisStartResponse)
async def start_live_analysis(
    payload: LiveAnalysisStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Trigger the analysis pipeline after all chunks have been uploaded.

    This endpoint:
      1. Creates a LiveAnalysisJob record (status=pending)
      2. Creates/updates a Video record in the videos table (for History view)
      3. Enqueues a worker job for the analysis pipeline
      4. Returns the job ID for status polling

    Called by the LiveBoost iOS app after ChunkUploadService
    confirms all chunks are uploaded.
    """
    try:
        user_id = current_user["id"]
        video_id = payload.video_id

        # Check for duplicate: prevent re-triggering for same video_id
        existing = await db.execute(
            select(LiveAnalysisJob).where(
                LiveAnalysisJob.video_id == video_id,
                LiveAnalysisJob.user_id == user_id,
            )
        )
        existing_job = existing.scalar_one_or_none()
        if existing_job:
            # If already exists and not failed, return existing job
            if existing_job.status not in ("failed",):
                return LiveAnalysisStartResponse(
                    job_id=str(existing_job.id),
                    video_id=video_id,
                    status=existing_job.status,
                    message="Analysis job already exists",
                )
            else:
                # Reset failed job for retry
                existing_job.status = "pending"
                existing_job.current_step = None
                existing_job.progress = 0
                existing_job.error_message = None
                existing_job.started_at = None
                existing_job.completed_at = None
                existing_job.results = None
                await db.commit()
                await db.refresh(existing_job)
                job = existing_job

                # BUILD 28: Also reset the videos table record for retry
                await _ensure_video_record(db, video_id, user_id, "pending")
                await db.commit()
        else:
            # Create new job
            job = LiveAnalysisJob(
                id=uuid_module.uuid4(),
                video_id=video_id,
                user_id=user_id,
                stream_source=payload.stream_source,
                status="pending",
                total_chunks=payload.total_chunks,
                progress=0,
            )
            db.add(job)

            # BUILD 28: Also create a record in the videos table
            await _ensure_video_record(db, video_id, user_id, "uploaded")

            await db.commit()
            await db.refresh(job)

        # Enqueue worker job
        queue_payload = {
            "job_type": "live_analysis",
            "job_id": str(job.id),
            "video_id": video_id,
            "user_id": user_id,
            "stream_source": payload.stream_source,
            "total_chunks": payload.total_chunks,
            "email": current_user.get("email", ""),
        }

        enqueue_result = await enqueue_job(queue_payload)

        # Persist enqueue evidence
        try:
            if enqueue_result.success:
                await db.execute(
                    update(LiveAnalysisJob)
                    .where(LiveAnalysisJob.id == job.id)
                    .values(
                        queue_message_id=enqueue_result.message_id,
                        queue_enqueued_at=enqueue_result.enqueued_at,
                        started_at=datetime.now(timezone.utc),
                    )
                )
                logger.info(
                    f"[live-analysis] Enqueued OK job={job.id} video={video_id} "
                    f"msg_id={enqueue_result.message_id}"
                )
            else:
                await db.execute(
                    update(LiveAnalysisJob)
                    .where(LiveAnalysisJob.id == job.id)
                    .values(
                        status="failed",
                        error_message=f"Failed to enqueue: {enqueue_result.error}",
                    )
                )
                # BUILD 28: Also update videos table on enqueue failure
                try:
                    await db.execute(
                        text("""
                            UPDATE videos
                            SET status = 'ERROR', updated_at = now()
                            WHERE id = :video_id
                        """),
                        {"video_id": video_id},
                    )
                except Exception:
                    pass
                logger.error(
                    f"[live-analysis] Enqueue FAILED job={job.id} error={enqueue_result.error}"
                )
            await db.commit()
        except Exception as db_err:
            logger.error(f"[live-analysis] Failed to save enqueue evidence: {db_err}")
            try:
                await db.rollback()
            except Exception as _e:
                logger.debug(f"Non-critical error suppressed: {_e}")

        return LiveAnalysisStartResponse(
            job_id=str(job.id),
            video_id=video_id,
            status="pending" if enqueue_result.success else "failed",
            message=(
                "Analysis pipeline started"
                if enqueue_result.success
                else f"Failed to start analysis: {enqueue_result.error}"
            ),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"[live-analysis/start] Unexpected error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start analysis: {exc}",
        )


# ──────────────────────────────────────────────
# 2. Get Analysis Status
# ──────────────────────────────────────────────
@router.get("/status/{video_id}", response_model=LiveAnalysisStatusResponse)
async def get_analysis_status(
    video_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Poll the current status of a live analysis job.

    Returns the job status, current processing step, progress percentage,
    and results (when completed).
    """
    try:
        user_id = current_user["id"]

        result = await db.execute(
            select(LiveAnalysisJob).where(
                LiveAnalysisJob.video_id == video_id,
                LiveAnalysisJob.user_id == user_id,
            ).order_by(LiveAnalysisJob.created_at.desc())
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No analysis job found for video_id={video_id}",
            )

        # Parse results if available
        analysis_results = None
        if job.results:
            try:
                analysis_results = AnalysisResults(**job.results)
            except Exception:
                analysis_results = AnalysisResults(
                    top_sales_moments=[],
                    hook_candidates=[],
                    clip_candidates=[],
                )

        return LiveAnalysisStatusResponse(
            job_id=str(job.id),
            video_id=job.video_id,
            status=job.status,
            current_step=job.current_step,
            progress=job.progress,
            started_at=job.started_at,
            completed_at=job.completed_at,
            results=analysis_results,
            error_message=job.error_message,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"[live-analysis/status] Unexpected error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get analysis status: {exc}",
        )


# ──────────────────────────────────────────────
# 3. Generate Chunk Upload URL
# ──────────────────────────────────────────────
@router.post(
    "/generate-chunk-upload-url",
    response_model=GenerateChunkUploadURLResponse,
)
async def generate_chunk_upload_url(
    payload: GenerateChunkUploadURLRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Generate a signed upload URL for a single video chunk.

    The LiveBoost iOS app calls this for each 10MB chunk during
    recording. Chunks are stored under:
      {email}/{video_id}/chunks/chunk_{XXXX}.mp4

    After all chunks are uploaded, the iOS app calls /start to
    trigger the assembly + analysis pipeline.
    """
    try:
        email = current_user.get("email", "")
        video_id = payload.video_id
        chunk_index = payload.chunk_index

        # Generate chunk filename
        chunk_filename = f"chunks/chunk_{chunk_index:04d}.mp4"

        # Use existing storage service to generate SAS URL
        vid, upload_url, blob_url, expiry = await generate_upload_sas(
            email=email,
            video_id=video_id,
            filename=chunk_filename,
        )

        return GenerateChunkUploadURLResponse(
            video_id=video_id,
            chunk_index=chunk_index,
            upload_url=upload_url,
            blob_url=blob_url,
            expires_at=expiry,
        )

    except Exception as exc:
        logger.exception(f"[live-analysis/generate-chunk-upload-url] Error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate chunk upload URL: {exc}",
        )
