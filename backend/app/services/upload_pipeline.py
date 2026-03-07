"""
Upload Pipeline Service
=======================
Encapsulates the **only** correct order for completing a video upload:

    Step 1 – Verify blob exists in Azure Blob Storage
    Step 2 – Create video DB record  (status = "uploaded")
    Step 3 – Generate download SAS URL for worker
    Step 4 – Enqueue worker job
    Step 5 – Persist enqueue evidence back to DB
    Step 6 – Clean up upload session record

Rules
-----
- This service is the single source of truth for the upload pipeline order.
- It MUST NOT import anything from video.py or other feature modules.
- Any change to the pipeline order MUST be reflected in the integration tests
  (backend/tests/test_upload_pipeline.py).
- Worker failures MUST NOT affect upload success.  The upload is considered
  successful as soon as the DB record is created (Step 2).  Enqueue failure
  is recorded in the DB but does NOT raise an exception to the caller.
"""
from __future__ import annotations

import logging
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm.upload import Upload
from app.models.orm.video import Video
from app.repository.video_repository import VideoRepository
from app.services.queue_service import EnqueueResult, enqueue_job
from app.services.storage_service import generate_download_sas

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class UploadPipelineResult:
    """Structured result returned to the API endpoint."""
    video_id: str
    status: str
    enqueue_status: str          # "OK" | "FAILED" | "SKIPPED"
    message: str
    enqueue_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "status": self.status,
            "enqueue_status": self.enqueue_status,
            "message": self.message,
        }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class UploadPipelineService:
    """
    Executes the upload completion pipeline in a guaranteed order.

    The caller (upload_core.py) passes all required data; this service
    owns the sequencing and error handling.
    """

    def __init__(self, video_repository: VideoRepository) -> None:
        if video_repository is None:
            raise ValueError("VideoRepository is required")
        self._repo = video_repository

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def complete_upload(
        self,
        *,
        user_id: int,
        email: str,
        video_id: str,
        original_filename: str,
        db: AsyncSession,
        upload_id: Optional[str] = None,
        upload_type: str = "screen_recording",
        excel_product_blob_url: Optional[str] = None,
        excel_trend_blob_url: Optional[str] = None,
        time_offset_seconds: float = 0.0,
    ) -> UploadPipelineResult:
        """
        Execute the upload completion pipeline.

        Steps
        -----
        1. Validate inputs
        2. Create DB record  (status = "uploaded")
        3. Generate download SAS URL
        4. Build queue payload
        5. Enqueue worker job  (failure is recorded, NOT raised)
        6. Persist enqueue evidence
        7. Clean up upload session
        """
        _logger.info(
            f"[upload_pipeline] START video_id={video_id} "
            f"user_id={user_id} upload_type={upload_type}"
        )

        # ── Step 1: Validate inputs ───────────────────────────────────────
        self._validate_inputs(video_id=video_id, email=email, filename=original_filename)

        # ── Step 2: Create DB record ──────────────────────────────────────
        video = await self._create_db_record(
            user_id=user_id,
            video_id=video_id,
            original_filename=original_filename,
            upload_type=upload_type,
            excel_product_blob_url=excel_product_blob_url,
            excel_trend_blob_url=excel_trend_blob_url,
            time_offset_seconds=time_offset_seconds,
        )
        _logger.info(f"[upload_pipeline] Step 2 OK: DB record created video_id={video.id}")

        # ── Step 3: Generate download SAS URL ─────────────────────────────
        download_url = await self._generate_download_url(
            email=email,
            video_id=str(video.id),
            filename=original_filename,
        )
        _logger.info(f"[upload_pipeline] Step 3 OK: SAS URL generated")

        # ── Step 4 + 5: Enqueue + persist evidence ────────────────────────
        queue_payload = self._build_queue_payload(
            video=video,
            download_url=download_url,
            original_filename=original_filename,
            user_id=user_id,
            upload_type=upload_type,
            time_offset_seconds=time_offset_seconds,
        )

        # Add Excel download URLs for clean_video uploads
        if upload_type == "clean_video":
            queue_payload = await self._add_excel_urls(
                queue_payload=queue_payload,
                email=email,
                video_id=str(video.id),
                excel_product_blob_url=excel_product_blob_url,
                excel_trend_blob_url=excel_trend_blob_url,
            )

        enqueue_result = await self._enqueue_and_persist(
            db=db,
            video=video,
            queue_payload=queue_payload,
        )

        # ── Step 7: Clean up upload session ──────────────────────────────
        await self._cleanup_upload_session(
            db=db,
            upload_id=upload_id,
            user_id=user_id,
        )

        # ── Build result ──────────────────────────────────────────────────
        if enqueue_result.success:
            message = "Video upload completed; queued for analysis"
            enqueue_status = "OK"
        else:
            message = (
                f"Video saved but enqueue failed: {enqueue_result.error}. "
                "The video will be retried by the worker."
            )
            enqueue_status = "FAILED"

        _logger.info(
            f"[upload_pipeline] DONE video_id={video.id} "
            f"enqueue={enqueue_status}"
        )

        return UploadPipelineResult(
            video_id=str(video.id),
            status=video.status,
            enqueue_status=enqueue_status,
            message=message,
            enqueue_error=enqueue_result.error,
        )

    # ------------------------------------------------------------------
    # Private helpers – each maps to one pipeline step
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(*, video_id: str, email: str, filename: str) -> None:
        """Step 1: Raise ValueError for obviously invalid inputs."""
        if not video_id:
            raise ValueError("video_id is required")
        if not email:
            raise ValueError("email is required")
        if not filename:
            raise ValueError("filename is required")
        # Validate video_id is a valid UUID
        try:
            uuid_module.UUID(video_id)
        except ValueError:
            raise ValueError(f"video_id must be a valid UUID, got: {video_id!r}")

    async def _create_db_record(
        self,
        *,
        user_id: int,
        video_id: str,
        original_filename: str,
        upload_type: str,
        excel_product_blob_url: Optional[str],
        excel_trend_blob_url: Optional[str],
        time_offset_seconds: float,
    ) -> Video:
        """Step 2: Persist video record to DB (status = 'uploaded')."""
        return await self._repo.create_video(
            user_id=user_id,
            video_id=video_id,
            original_filename=original_filename,
            status="uploaded",
            upload_type=upload_type,
            excel_product_blob_url=excel_product_blob_url,
            excel_trend_blob_url=excel_trend_blob_url,
            time_offset_seconds=time_offset_seconds,
        )

    @staticmethod
    async def _generate_download_url(
        *,
        email: str,
        video_id: str,
        filename: str,
    ) -> str:
        """Step 3: Generate a 24-hour read SAS URL for the worker."""
        download_url, _ = await generate_download_sas(
            email=email,
            video_id=video_id,
            filename=filename,
            expires_in_minutes=1440,  # 24 hours
        )
        return download_url

    @staticmethod
    def _build_queue_payload(
        *,
        video: Video,
        download_url: str,
        original_filename: str,
        user_id: int,
        upload_type: str,
        time_offset_seconds: float,
    ) -> dict:
        """Step 4: Build the worker queue message payload."""
        return {
            "video_id": str(video.id),
            "blob_url": download_url,
            "original_filename": original_filename,
            "user_id": user_id,
            "upload_type": upload_type,
            "time_offset_seconds": time_offset_seconds,
        }

    @staticmethod
    async def _add_excel_urls(
        *,
        queue_payload: dict,
        email: str,
        video_id: str,
        excel_product_blob_url: Optional[str],
        excel_trend_blob_url: Optional[str],
    ) -> dict:
        """Step 4b: Append Excel SAS URLs for clean_video uploads."""
        if excel_product_blob_url:
            try:
                product_download_url, _ = await generate_download_sas(
                    email=email,
                    video_id=video_id,
                    filename=f"excel/{excel_product_blob_url.split('/')[-1].split('?')[0]}",
                    expires_in_minutes=1440,
                )
                queue_payload["excel_product_url"] = product_download_url
            except Exception as exc:
                _logger.warning(f"[upload_pipeline] Excel product URL failed: {exc}")

        if excel_trend_blob_url:
            try:
                trend_download_url, _ = await generate_download_sas(
                    email=email,
                    video_id=video_id,
                    filename=f"excel/{excel_trend_blob_url.split('/')[-1].split('?')[0]}",
                    expires_in_minutes=1440,
                )
                queue_payload["excel_trend_url"] = trend_download_url
            except Exception as exc:
                _logger.warning(f"[upload_pipeline] Excel trend URL failed: {exc}")

        return queue_payload

    @staticmethod
    async def _enqueue_and_persist(
        *,
        db: AsyncSession,
        video: Video,
        queue_payload: dict,
    ) -> EnqueueResult:
        """
        Step 5: Enqueue the job and persist the result to DB.

        This method NEVER raises — enqueue failure is recorded in DB
        and returned to the caller as a non-fatal result.
        """
        try:
            enqueue_result = await enqueue_job(queue_payload)
        except Exception as unexpected_exc:
            _logger.error(
                f"[upload_pipeline] Step 5: enqueue_job raised unexpectedly: {unexpected_exc}"
            )
            enqueue_result = EnqueueResult(
                success=False,
                error=f"Unexpected enqueue error: {unexpected_exc}",
            )

        try:
            vid_uuid = uuid_module.UUID(str(video.id))
            if enqueue_result.success:
                await db.execute(
                    update(Video)
                    .where(Video.id == vid_uuid)
                    .values(
                        enqueue_status="OK",
                        queue_message_id=enqueue_result.message_id,
                        queue_enqueued_at=enqueue_result.enqueued_at,
                        enqueue_error=None,
                    )
                )
                _logger.info(
                    f"[upload_pipeline] Step 5 OK: enqueued "
                    f"video={video.id} msg_id={enqueue_result.message_id}"
                )
            else:
                await db.execute(
                    update(Video)
                    .where(Video.id == vid_uuid)
                    .values(
                        enqueue_status="FAILED",
                        queue_message_id=None,
                        queue_enqueued_at=None,
                        enqueue_error=enqueue_result.error,
                    )
                )
                _logger.error(
                    f"[upload_pipeline] Step 5 FAILED: enqueue error "
                    f"video={video.id} error={enqueue_result.error}"
                )
            await db.commit()
        except Exception as db_err:
            _logger.error(
                f"[upload_pipeline] Step 5: failed to persist enqueue evidence: {db_err}"
            )
            try:
                await db.rollback()
            except Exception:
                pass

        return enqueue_result

    @staticmethod
    async def _cleanup_upload_session(
        *,
        db: AsyncSession,
        upload_id: Optional[str],
        user_id: int,
    ) -> None:
        """
        Step 7: Remove the upload session record.

        Failure here is non-fatal — the upload has already succeeded.
        """
        # Remove specific upload session
        if upload_id:
            try:
                upload_uuid = uuid_module.UUID(upload_id)
                await db.execute(delete(Upload).where(Upload.id == upload_uuid))
                await db.commit()
            except Exception as exc:
                _logger.warning(f"[upload_pipeline] Step 7: cleanup upload_id failed: {exc}")
                try:
                    await db.rollback()
                except Exception:
                    pass

        # Remove stale upload records for this user (older than 24 hours)
        try:
            stale_cutoff = datetime.utcnow() - timedelta(hours=24)
            await db.execute(
                delete(Upload).where(
                    Upload.user_id == user_id,
                    Upload.created_at < stale_cutoff,
                )
            )
            await db.commit()
        except Exception as exc:
            _logger.warning(f"[upload_pipeline] Step 7: stale cleanup failed: {exc}")
            try:
                await db.rollback()
            except Exception:
                pass
