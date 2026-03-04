from app.services.storage_service import generate_upload_sas, generate_download_sas, generate_blob_name
from app.repository.video_repository import VideoRepository
from app.services.queue_service import enqueue_job
from app.core.container import Container
from app.models.orm.upload import Upload
from app.models.orm.user import User
from app.models.orm.video import Video
from datetime import datetime, timedelta
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
import os
import asyncio
import uuid as uuid_module


_logger = logging.getLogger(__name__)


class VideoService:
    """Service layer for video operations"""

    def __init__(self, video_repository: VideoRepository | None = None):
        self.video_repository = video_repository

    async def generate_upload_url(self, email: str, db: AsyncSession, video_id: str | None = None, filename: str | None = None):
        """Generate SAS upload URL for video file and create Upload record for resumable uploads"""
        vid, upload_url, blob_url, expiry = await generate_upload_sas(
            email=email,
            video_id=video_id,
            filename=filename,
        )
        
        # Find user by email
        user_id = None
        try:
            result = await db.execute(
                select(User).where(User.email == email)
            )
            user = result.scalar_one_or_none()
            if user:
                user_id = user.id
        except Exception:
            # If user lookup fails, continue with user_id=None
            pass
        
        # Create Upload record for tracking resumable session
        upload_id = str(uuid_module.uuid4())
        
        upload_record = Upload(
            id=uuid_module.UUID(upload_id),
            user_id=user_id,
            upload_url=upload_url,
        )
        
        db.add(upload_record)
        await db.commit()

        return {
            "video_id": vid,
            "upload_id": upload_id,
            "upload_url": upload_url,
            "blob_url": blob_url,
            "expires_at": expiry,
        }

    async def generate_excel_upload_urls(self, email: str, video_id: str, product_filename: str, trend_filename: str):
        """Generate SAS upload URLs for Excel files (product + trend_stats)"""
        # Generate upload URL for product Excel
        product_blob_name = f"{email}/{video_id}/excel/{product_filename}"
        _, product_upload_url, product_blob_url, expiry = await generate_upload_sas(
            email=email,
            video_id=video_id,
            filename=f"excel/{product_filename}",
        )

        # Generate upload URL for trend stats Excel
        _, trend_upload_url, trend_blob_url, _ = await generate_upload_sas(
            email=email,
            video_id=video_id,
            filename=f"excel/{trend_filename}",
        )

        return {
            "video_id": video_id,
            "product_upload_url": product_upload_url,
            "product_blob_url": product_blob_url,
            "trend_upload_url": trend_upload_url,
            "trend_blob_url": trend_blob_url,
            "expires_at": expiry,
        }

    async def generate_download_url(self, email: str, video_id: str, filename: str | None = None, expires_in_minutes: int | None = None):
        """Generate SAS download URL for video file"""
        download_url, expiry = await generate_download_sas(
            email=email,
            video_id=video_id,
            filename=filename,
            expires_in_minutes=expires_in_minutes,
        )
        return {
            "video_id": video_id,
            "download_url": download_url,
            "expires_at": expiry,
        }

    async def handle_upload(self, db, blob_url):
        """Handle video upload completion"""
        pass

    async def handle_upload_complete(
        self,
        user_id: int,
        email: str,
        video_id: str,
        original_filename: str,
        db: AsyncSession,
        upload_id: str | None = None,
        upload_type: str = "screen_recording",
        excel_product_blob_url: str | None = None,
        excel_trend_blob_url: str | None = None,
        time_offset_seconds: float = 0,
    ) -> dict:
        """Handle video upload completion - save to database and remove upload session"""
        if not self.video_repository:
            raise RuntimeError("VideoRepository not initialized")
        
        # 1) Persist video record (status=uploaded)
        video = await self.video_repository.create_video(
            user_id=user_id,
            video_id=video_id,
            original_filename=original_filename,
            status="uploaded",
            upload_type=upload_type,
            excel_product_blob_url=excel_product_blob_url,
            excel_trend_blob_url=excel_trend_blob_url,
            time_offset_seconds=time_offset_seconds,
        )

        # 2) Generate download SAS URL so worker can fetch the video
        download_url, _ = await generate_download_sas(
            email=email,
            video_id=str(video.id),
            filename=original_filename,
            expires_in_minutes=1440,  # 24h for processing
        )

        # 3) Build queue payload
        queue_payload = {
            "video_id": str(video.id),
            "blob_url": download_url,  # SAS URL with read permission
            "original_filename": original_filename,
            "user_id": user_id,
            "upload_type": upload_type,
            "time_offset_seconds": time_offset_seconds,
        }

        # For clean_video uploads, generate download URLs for Excel files
        if upload_type == "clean_video":
            if excel_product_blob_url:
                try:
                    product_download_url, _ = await generate_download_sas(
                        email=email,
                        video_id=str(video.id),
                        filename=f"excel/{excel_product_blob_url.split('/')[-1].split('?')[0]}",
                        expires_in_minutes=1440,
                    )
                    queue_payload["excel_product_url"] = product_download_url
                except Exception as e:
                    _logger.warning(f"Failed to generate product Excel download URL: {e}")

            if excel_trend_blob_url:
                try:
                    trend_download_url, _ = await generate_download_sas(
                        email=email,
                        video_id=str(video.id),
                        filename=f"excel/{excel_trend_blob_url.split('/')[-1].split('?')[0]}",
                        expires_in_minutes=1440,
                    )
                    queue_payload["excel_trend_url"] = trend_download_url
                except Exception as e:
                    _logger.warning(f"Failed to generate trend Excel download URL: {e}")

        # 4) Enqueue a message so worker can start processing
        #    Save enqueue evidence to DB regardless of success/failure
        enqueue_result = await enqueue_job(queue_payload)

        try:
            vid_uuid = uuid_module.UUID(str(video.id))
            if enqueue_result.success:
                await db.execute(
                    update(Video).where(Video.id == vid_uuid).values(
                        enqueue_status="OK",
                        queue_message_id=enqueue_result.message_id,
                        queue_enqueued_at=enqueue_result.enqueued_at,
                        enqueue_error=None,
                    )
                )
                _logger.info(f"[enqueue] OK video={video.id} msg_id={enqueue_result.message_id}")
            else:
                await db.execute(
                    update(Video).where(Video.id == vid_uuid).values(
                        enqueue_status="FAILED",
                        queue_message_id=None,
                        queue_enqueued_at=None,
                        enqueue_error=enqueue_result.error,
                    )
                )
                _logger.error(f"[enqueue] FAILED video={video.id} error={enqueue_result.error}")
            await db.commit()
        except Exception as db_err:
            _logger.error(f"[enqueue] Failed to save enqueue evidence: {db_err}")
            try:
                await db.rollback()
            except Exception:
                pass

        # Remove upload session record if present
        if upload_id:
            try:
                from uuid import UUID as _UUID
                upload_uuid = _UUID(upload_id)
                await db.execute(
                    delete(Upload).where(Upload.id == upload_uuid)
                )
                await db.commit()
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass

        # Clean up stale upload records for this user (older than 24 hours)
        # Do NOT delete all records - other uploads may be in progress
        try:
            from datetime import datetime, timedelta
            stale_cutoff = datetime.utcnow() - timedelta(hours=24)
            await db.execute(
                delete(Upload).where(
                    Upload.user_id == user_id,
                    Upload.created_at < stale_cutoff,
                )
            )
            await db.commit()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

        return {
            "video_id": str(video.id),
            "status": video.status,
            "enqueue_status": enqueue_result.success and "OK" or "FAILED",
            "message": "Video upload completed; queued for analysis" if enqueue_result.success
                       else f"Video saved but enqueue failed: {enqueue_result.error}",
        }
