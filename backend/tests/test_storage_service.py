"""Tests for storage_service.generate_read_sas_from_url.

These tests mock Azure SDK calls so they can run without real credentials.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set required env vars before importing the module
os.environ.setdefault("AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=https;"
    "AccountName=teststorage;"
    "AccountKey=dGVzdGtleQ==;"
    "EndpointSuffix=core.windows.net"
)
os.environ.setdefault("AZURE_STORAGE_ACCOUNT_NAME", "teststorage")
os.environ.setdefault("AZURE_BLOB_CONTAINER", "videos")


class TestGenerateReadSasFromUrl:
    """Tests for generate_read_sas_from_url."""

    @patch("app.services.storage_service.generate_blob_sas", return_value="sig=mock_sas_token")
    def test_basic_blob_url(self, mock_sas):
        """Standard Azure blob URL should produce a valid SAS URL."""
        from app.services.storage_service import generate_read_sas_from_url

        url = "https://teststorage.blob.core.windows.net/videos/user@example.com/abc123/abc123.mp4"
        result = generate_read_sas_from_url(url)

        assert result is not None
        assert result.startswith("https://teststorage.blob.core.windows.net/videos/")
        assert "sig=mock_sas_token" in result
        mock_sas.assert_called_once()
        # Verify blob_name was extracted correctly
        call_kwargs = mock_sas.call_args
        assert call_kwargs.kwargs["blob_name"] == "user@example.com/abc123/abc123.mp4"
        assert call_kwargs.kwargs["container_name"] == "videos"

    @patch("app.services.storage_service.generate_blob_sas", return_value="sig=mock_sas_token")
    def test_url_with_existing_query_string(self, mock_sas):
        """URL with existing (expired) SAS should strip old query and add new one."""
        from app.services.storage_service import generate_read_sas_from_url

        url = "https://teststorage.blob.core.windows.net/videos/user/vid/file.mp4?sv=2021-08-06&sig=old_expired"
        result = generate_read_sas_from_url(url)

        assert result is not None
        assert "sig=mock_sas_token" in result
        assert "sig=old_expired" not in result
        # blob_name should not contain query string
        call_kwargs = mock_sas.call_args
        assert "?" not in call_kwargs.kwargs["blob_name"]

    @patch("app.services.storage_service.generate_blob_sas", return_value="sig=mock_sas_token")
    def test_cdn_url_with_videos_in_path(self, mock_sas):
        """CDN URL that still has /videos/ in path should work."""
        from app.services.storage_service import generate_read_sas_from_url

        url = "https://cdn.aitherhub.com/videos/user/vid/clips/clip_0_60.mp4"
        result = generate_read_sas_from_url(url)

        assert result is not None
        call_kwargs = mock_sas.call_args
        assert call_kwargs.kwargs["blob_name"] == "user/vid/clips/clip_0_60.mp4"

    @patch("app.services.storage_service.generate_blob_sas", return_value="sig=mock_sas_token")
    def test_nested_blob_path(self, mock_sas):
        """Deeply nested blob paths (reportvideo, excel) should be preserved."""
        from app.services.storage_service import generate_read_sas_from_url

        url = "https://teststorage.blob.core.windows.net/videos/user/vid/reportvideo/0.0_104.0.mp4"
        result = generate_read_sas_from_url(url)

        assert result is not None
        call_kwargs = mock_sas.call_args
        assert call_kwargs.kwargs["blob_name"] == "user/vid/reportvideo/0.0_104.0.mp4"

    @patch("app.services.storage_service.generate_blob_sas", return_value="sig=mock_sas_token")
    def test_custom_container(self, mock_sas):
        """Custom container name should be used for lookup."""
        from app.services.storage_service import generate_read_sas_from_url

        url = "https://teststorage.blob.core.windows.net/reports/user/vid/report.pdf"
        result = generate_read_sas_from_url(url, container="reports")

        assert result is not None
        call_kwargs = mock_sas.call_args
        assert call_kwargs.kwargs["container_name"] == "reports"
        assert call_kwargs.kwargs["blob_name"] == "user/vid/report.pdf"

    @patch("app.services.storage_service.generate_blob_sas", return_value="sig=mock_sas_token")
    def test_custom_expiry(self, mock_sas):
        """Custom expiry hours should be respected."""
        from app.services.storage_service import generate_read_sas_from_url

        url = "https://teststorage.blob.core.windows.net/videos/user/vid/file.mp4"
        result = generate_read_sas_from_url(url, expires_hours=1)

        assert result is not None
        call_kwargs = mock_sas.call_args
        expiry = call_kwargs.kwargs["expiry"]
        # Expiry should be roughly 1 hour from now
        diff = (expiry - datetime.now(timezone.utc)).total_seconds()
        assert 3500 < diff < 3700  # ~1 hour

    def test_url_without_container_returns_none(self):
        """URL without the container name in path should return None."""
        from app.services.storage_service import generate_read_sas_from_url

        url = "https://example.com/some/random/path.mp4"
        result = generate_read_sas_from_url(url)
        assert result is None

    @patch("app.services.storage_service.CONNECTION_STRING", None)
    def test_no_connection_string_returns_none(self):
        """Missing connection string should return None gracefully."""
        from app.services.storage_service import generate_read_sas_from_url

        url = "https://teststorage.blob.core.windows.net/videos/user/vid/file.mp4"
        result = generate_read_sas_from_url(url)
        assert result is None

    @patch("app.services.storage_service.generate_blob_sas", side_effect=Exception("Azure SDK error"))
    def test_sdk_error_returns_none(self, mock_sas):
        """Azure SDK errors should be caught and return None."""
        from app.services.storage_service import generate_read_sas_from_url

        url = "https://teststorage.blob.core.windows.net/videos/user/vid/file.mp4"
        result = generate_read_sas_from_url(url)
        assert result is None


class TestGenerateBlobName:
    """Tests for generate_blob_name."""

    def test_basic(self):
        from app.services.storage_service import generate_blob_name
        result = generate_blob_name("user@example.com", "vid123")
        assert result == "user@example.com/vid123/vid123.mp4"

    def test_with_filename(self):
        from app.services.storage_service import generate_blob_name
        result = generate_blob_name("user@example.com", "vid123", "video.mp4")
        assert result == "user@example.com/vid123/vid123.mp4"

    def test_with_path_filename(self):
        from app.services.storage_service import generate_blob_name
        result = generate_blob_name("user@example.com", "vid123", "reportvideo/0.0_104.0.mp4")
        assert result == "user@example.com/vid123/reportvideo/0.0_104.0.mp4"

    def test_with_xlsx_extension(self):
        from app.services.storage_service import generate_blob_name
        result = generate_blob_name("user@example.com", "vid123", "data.xlsx")
        assert result == "user@example.com/vid123/vid123.xlsx"
