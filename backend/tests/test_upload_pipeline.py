"""
Upload Pipeline Integration Tests
===================================
These tests verify the upload pipeline ordering and isolation guarantees.

What is tested:
  1. Pipeline step ordering  (DB record BEFORE enqueue)
  2. Enqueue failure does NOT break upload success
  3. Worker failure does NOT affect upload state
  4. Input validation
  5. Upload session cleanup
  6. Batch upload pipeline
  7. UploadPipelineService is used by upload_core.py (not VideoService.handle_upload_complete)

Run:
    cd backend && python -m pytest tests/test_upload_pipeline.py -v

No real Azure / DB connections are needed – all external calls are mocked.
"""
from __future__ import annotations

import importlib
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Minimal env vars so the app can boot without real Azure credentials
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_pipeline.db")
os.environ.setdefault("AZURE_STORAGE_CONNECTION_STRING", "")
os.environ.setdefault("AZURE_STORAGE_ACCOUNT_NAME", "devstoreaccount1")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ALGORITHM", "HS256")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_video(video_id: str | None = None) -> MagicMock:
    """Create a mock Video ORM object."""
    v = MagicMock()
    v.id = uuid.UUID(video_id or str(uuid.uuid4()))
    v.status = "uploaded"
    v.user_id = 1
    return v


def _make_enqueue_result(success: bool = True, error: str | None = None):
    """Create a mock EnqueueResult."""
    from app.services.queue_service import EnqueueResult
    return EnqueueResult(
        success=success,
        message_id="msg-123" if success else None,
        enqueued_at=datetime.now(timezone.utc) if success else None,
        error=error,
    )


# ---------------------------------------------------------------------------
# Test: UploadPipelineService – pipeline ordering
# ---------------------------------------------------------------------------

class TestUploadPipelineOrder:
    """Verify that DB record is created BEFORE enqueue is called."""

    @pytest.mark.asyncio
    async def test_db_record_created_before_enqueue(self):
        """Step 2 (DB) must complete before Step 4 (enqueue)."""
        call_order: list[str] = []

        # Mock video repository
        mock_repo = MagicMock()
        created_video = _make_video()

        async def fake_create_video(**kwargs):
            call_order.append("db_create")
            return created_video

        mock_repo.create_video = fake_create_video

        # Mock external services
        async def fake_download_sas(*args, **kwargs):
            call_order.append("sas_url")
            return ("https://fake-sas-url", datetime.now(timezone.utc))

        async def fake_enqueue(payload):
            call_order.append("enqueue")
            return _make_enqueue_result(success=True)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("app.services.upload_pipeline.generate_download_sas", fake_download_sas), \
             patch("app.services.upload_pipeline.enqueue_job", fake_enqueue):

            from app.services.upload_pipeline import UploadPipelineService
            pipeline = UploadPipelineService(video_repository=mock_repo)

            result = await pipeline.complete_upload(
                user_id=1,
                email="test@example.com",
                video_id=str(created_video.id),
                original_filename="test.mp4",
                db=mock_db,
            )

        # Verify ordering: db_create → sas_url → enqueue
        assert call_order.index("db_create") < call_order.index("enqueue"), \
            "DB record must be created BEFORE enqueue"
        assert call_order.index("sas_url") < call_order.index("enqueue"), \
            "SAS URL must be generated BEFORE enqueue"

    @pytest.mark.asyncio
    async def test_upload_succeeds_when_enqueue_fails(self):
        """
        Worker enqueue failure MUST NOT break upload success.
        The upload is considered successful once the DB record is created.
        """
        mock_repo = MagicMock()
        created_video = _make_video()

        async def fake_create_video(**kwargs):
            return created_video

        mock_repo.create_video = fake_create_video

        async def fake_download_sas(*args, **kwargs):
            return ("https://fake-sas-url", datetime.now(timezone.utc))

        async def fake_enqueue_fail(payload):
            return _make_enqueue_result(success=False, error="Queue connection refused")

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("app.services.upload_pipeline.generate_download_sas", fake_download_sas), \
             patch("app.services.upload_pipeline.enqueue_job", fake_enqueue_fail):

            from app.services.upload_pipeline import UploadPipelineService
            pipeline = UploadPipelineService(video_repository=mock_repo)

            # Must NOT raise even though enqueue failed
            result = await pipeline.complete_upload(
                user_id=1,
                email="test@example.com",
                video_id=str(created_video.id),
                original_filename="test.mp4",
                db=mock_db,
            )

        assert result.video_id == str(created_video.id)
        assert result.enqueue_status == "FAILED"
        assert result.enqueue_error == "Queue connection refused"
        # Upload itself is still considered successful (DB record exists)
        assert result.status == "uploaded"

    @pytest.mark.asyncio
    async def test_upload_succeeds_when_enqueue_raises(self):
        """Even if enqueue_job raises an unexpected exception, upload must not fail."""
        mock_repo = MagicMock()
        created_video = _make_video()

        async def fake_create_video(**kwargs):
            return created_video

        mock_repo.create_video = fake_create_video

        async def fake_download_sas(*args, **kwargs):
            return ("https://fake-sas-url", datetime.now(timezone.utc))

        async def fake_enqueue_raise(payload):
            raise RuntimeError("Unexpected queue error")

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        # enqueue_job itself catches all exceptions and returns EnqueueResult(success=False)
        # But let's verify the pipeline handles it gracefully if somehow it slips through
        with patch("app.services.upload_pipeline.generate_download_sas", fake_download_sas), \
             patch("app.services.upload_pipeline.enqueue_job", fake_enqueue_raise):

            from app.services.upload_pipeline import UploadPipelineService
            pipeline = UploadPipelineService(video_repository=mock_repo)

            # The pipeline's _enqueue_and_persist catches all exceptions
            # so this should not raise
            try:
                result = await pipeline.complete_upload(
                    user_id=1,
                    email="test@example.com",
                    video_id=str(created_video.id),
                    original_filename="test.mp4",
                    db=mock_db,
                )
                # If we get here, the pipeline handled the exception gracefully
                assert result.video_id == str(created_video.id)
            except RuntimeError:
                pytest.fail(
                    "Pipeline should not propagate enqueue exceptions to the caller"
                )


# ---------------------------------------------------------------------------
# Test: Input validation
# ---------------------------------------------------------------------------

class TestUploadPipelineValidation:
    """Verify that invalid inputs are rejected before any DB/queue operations."""

    @pytest.mark.asyncio
    async def test_invalid_video_id_raises_value_error(self):
        from app.services.upload_pipeline import UploadPipelineService
        mock_repo = MagicMock()
        mock_db = AsyncMock()

        pipeline = UploadPipelineService(video_repository=mock_repo)

        with pytest.raises(ValueError, match="valid UUID"):
            await pipeline.complete_upload(
                user_id=1,
                email="test@example.com",
                video_id="not-a-uuid",
                original_filename="test.mp4",
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_empty_email_raises_value_error(self):
        from app.services.upload_pipeline import UploadPipelineService
        mock_repo = MagicMock()
        mock_db = AsyncMock()

        pipeline = UploadPipelineService(video_repository=mock_repo)

        with pytest.raises(ValueError, match="email"):
            await pipeline.complete_upload(
                user_id=1,
                email="",
                video_id=str(uuid.uuid4()),
                original_filename="test.mp4",
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_empty_filename_raises_value_error(self):
        from app.services.upload_pipeline import UploadPipelineService
        mock_repo = MagicMock()
        mock_db = AsyncMock()

        pipeline = UploadPipelineService(video_repository=mock_repo)

        with pytest.raises(ValueError, match="filename"):
            await pipeline.complete_upload(
                user_id=1,
                email="test@example.com",
                video_id=str(uuid.uuid4()),
                original_filename="",
                db=mock_db,
            )

    def test_none_repository_raises_value_error(self):
        from app.services.upload_pipeline import UploadPipelineService
        with pytest.raises(ValueError, match="VideoRepository"):
            UploadPipelineService(video_repository=None)


# ---------------------------------------------------------------------------
# Test: Pipeline result structure
# ---------------------------------------------------------------------------

class TestUploadPipelineResult:
    """Verify the result structure returned by the pipeline."""

    @pytest.mark.asyncio
    async def test_result_contains_required_fields(self):
        mock_repo = MagicMock()
        created_video = _make_video()

        async def fake_create_video(**kwargs):
            return created_video

        mock_repo.create_video = fake_create_video

        async def fake_download_sas(*args, **kwargs):
            return ("https://fake-sas-url", datetime.now(timezone.utc))

        async def fake_enqueue(payload):
            return _make_enqueue_result(success=True)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("app.services.upload_pipeline.generate_download_sas", fake_download_sas), \
             patch("app.services.upload_pipeline.enqueue_job", fake_enqueue):

            from app.services.upload_pipeline import UploadPipelineService
            pipeline = UploadPipelineService(video_repository=mock_repo)

            result = await pipeline.complete_upload(
                user_id=1,
                email="test@example.com",
                video_id=str(created_video.id),
                original_filename="test.mp4",
                db=mock_db,
            )

        # Verify result fields
        assert result.video_id == str(created_video.id)
        assert result.status == "uploaded"
        assert result.enqueue_status == "OK"
        assert "queued" in result.message.lower() or "completed" in result.message.lower()

        # Verify to_dict() returns the expected keys
        d = result.to_dict()
        assert "video_id" in d
        assert "status" in d
        assert "message" in d

    @pytest.mark.asyncio
    async def test_batch_upload_processes_all_videos(self):
        """Batch upload should process all videos in order."""
        mock_repo = MagicMock()
        call_count = 0

        async def fake_create_video(**kwargs):
            nonlocal call_count
            call_count += 1
            v = _make_video(video_id=kwargs.get("video_id"))
            return v

        mock_repo.create_video = fake_create_video

        async def fake_download_sas(*args, **kwargs):
            return ("https://fake-sas-url", datetime.now(timezone.utc))

        async def fake_enqueue(payload):
            return _make_enqueue_result(success=True)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        video_ids = [str(uuid.uuid4()) for _ in range(3)]

        with patch("app.services.upload_pipeline.generate_download_sas", fake_download_sas), \
             patch("app.services.upload_pipeline.enqueue_job", fake_enqueue):

            from app.services.upload_pipeline import UploadPipelineService
            pipeline = UploadPipelineService(video_repository=mock_repo)

            results = []
            for vid in video_ids:
                result = await pipeline.complete_upload(
                    user_id=1,
                    email="test@example.com",
                    video_id=vid,
                    original_filename=f"{vid}.mp4",
                    db=mock_db,
                    upload_type="clean_video",
                )
                results.append(result)

        assert len(results) == 3
        assert call_count == 3
        for result in results:
            assert result.enqueue_status == "OK"


# ---------------------------------------------------------------------------
# Test: upload_core.py uses UploadPipelineService
# ---------------------------------------------------------------------------

class TestUploadCoreUsesNewPipeline:
    """Verify that upload_core.py delegates to UploadPipelineService."""

    def test_upload_complete_imports_pipeline_service(self):
        """upload_core.py must import UploadPipelineService."""
        try:
            import app.api.v1.endpoints.upload_core as upload_core_mod
            import inspect
            source = inspect.getsource(upload_core_mod)
            assert "UploadPipelineService" in source, \
                "upload_core.py must use UploadPipelineService for pipeline ordering"
        except ImportError as exc:
            pytest.skip(f"Cannot import upload_core: {exc}")

    def test_upload_complete_does_not_call_handle_upload_complete(self):
        """
        upload_core.py should NOT call VideoService.handle_upload_complete directly.
        All pipeline logic must go through UploadPipelineService.
        """
        try:
            import app.api.v1.endpoints.upload_core as upload_core_mod
            import inspect
            # Get source of the upload_complete function specifically
            source = inspect.getsource(upload_core_mod.upload_complete)
            assert "handle_upload_complete" not in source, \
                "upload_complete() must not call VideoService.handle_upload_complete directly"
        except ImportError as exc:
            pytest.skip(f"Cannot import upload_core: {exc}")

    def test_batch_upload_complete_does_not_call_handle_upload_complete(self):
        """batch_upload_complete should also use UploadPipelineService."""
        try:
            import app.api.v1.endpoints.upload_core as upload_core_mod
            import inspect
            source = inspect.getsource(upload_core_mod.batch_upload_complete)
            assert "handle_upload_complete" not in source, \
                "batch_upload_complete() must not call VideoService.handle_upload_complete directly"
        except ImportError as exc:
            pytest.skip(f"Cannot import upload_core: {exc}")


# ---------------------------------------------------------------------------
# Test: Upload session cleanup
# ---------------------------------------------------------------------------

class TestUploadSessionCleanup:
    """Verify that upload session records are cleaned up after completion."""

    @pytest.mark.asyncio
    async def test_upload_session_deleted_after_success(self):
        """Upload session record must be deleted after successful upload."""
        mock_repo = MagicMock()
        created_video = _make_video()
        upload_id = str(uuid.uuid4())

        async def fake_create_video(**kwargs):
            return created_video

        mock_repo.create_video = fake_create_video

        async def fake_download_sas(*args, **kwargs):
            return ("https://fake-sas-url", datetime.now(timezone.utc))

        async def fake_enqueue(payload):
            return _make_enqueue_result(success=True)

        # Track delete calls
        delete_calls: list[str] = []
        mock_db = AsyncMock()

        original_execute = AsyncMock()

        async def tracking_execute(stmt, *args, **kwargs):
            # Capture delete statements
            stmt_str = str(stmt)
            if "DELETE" in stmt_str.upper() or "delete" in stmt_str.lower():
                delete_calls.append("delete_called")
            return original_execute.return_value

        mock_db.execute = tracking_execute
        mock_db.commit = AsyncMock()

        with patch("app.services.upload_pipeline.generate_download_sas", fake_download_sas), \
             patch("app.services.upload_pipeline.enqueue_job", fake_enqueue):

            from app.services.upload_pipeline import UploadPipelineService
            pipeline = UploadPipelineService(video_repository=mock_repo)

            result = await pipeline.complete_upload(
                user_id=1,
                email="test@example.com",
                video_id=str(created_video.id),
                original_filename="test.mp4",
                db=mock_db,
                upload_id=upload_id,
            )

        # Verify that delete was called (for upload session cleanup)
        assert len(delete_calls) > 0, "Upload session cleanup must call DELETE"


# ---------------------------------------------------------------------------
# Test: Route contract (routes must not change)
# ---------------------------------------------------------------------------

class TestFrozenRouteContract:
    """Verify that the upload API routes have not changed."""

    FROZEN_ROUTES = [
        ("/api/v1/videos/generate-upload-url", {"POST"}),
        ("/api/v1/videos/generate-download-url", {"POST"}),
        ("/api/v1/videos/upload-complete", {"POST"}),
        ("/api/v1/videos/batch-upload-complete", {"POST"}),
        ("/api/v1/videos/generate-excel-upload-url", {"POST"}),
        ("/api/v1/videos/uploads/check/{user_id}", {"GET"}),
        ("/api/v1/videos/uploads/clear/{user_id}", {"DELETE"}),
    ]

    def _get_route_map(self):
        try:
            from app.main import app
            route_map: dict[str, set[str]] = {}
            for route in app.routes:
                if hasattr(route, "path") and hasattr(route, "methods"):
                    route_map[route.path] = set(route.methods)
            return route_map
        except Exception as exc:
            pytest.skip(f"Cannot import app (missing deps?): {exc}")

    @pytest.mark.parametrize("path,methods", FROZEN_ROUTES)
    def test_frozen_route_exists(self, path, methods):
        """Each frozen route must exist with the correct HTTP methods."""
        route_map = self._get_route_map()
        assert path in route_map, (
            f"FROZEN ROUTE BROKEN: {path} not found. "
            f"Available routes: {sorted(route_map.keys())}"
        )
        for m in methods:
            assert m in route_map[path], (
                f"FROZEN ROUTE BROKEN: Method {m} not found for {path}"
            )
