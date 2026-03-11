"""Tests for disk_guard module.

Tests core functions with mocked filesystem to avoid side effects.
"""

import os
import sys
import shutil
import tempfile
from unittest.mock import patch, MagicMock
from collections import namedtuple

import pytest

# Ensure worker/batch is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Mock heavy imports that disk_guard may pull in
sys.modules.setdefault("dotenv", MagicMock())

from disk_guard import (
    get_disk_info,
    ensure_disk_space,
    cleanup_video_files,
    _safe_remove_file,
    _safe_remove_dir,
)


DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])


class TestGetDiskInfo:
    """Tests for get_disk_info."""

    @patch("shutil.disk_usage")
    def test_returns_correct_structure(self, mock_usage):
        mock_usage.return_value = DiskUsage(
            total=100 * (1024 ** 3),  # 100 GB
            used=60 * (1024 ** 3),    # 60 GB
            free=40 * (1024 ** 3),    # 40 GB
        )
        info = get_disk_info()
        assert abs(info["total_gb"] - 100.0) < 0.01
        assert abs(info["used_gb"] - 60.0) < 0.01
        assert abs(info["free_gb"] - 40.0) < 0.01
        assert abs(info["used_pct"] - 60.0) < 0.01

    @patch("shutil.disk_usage")
    def test_high_usage(self, mock_usage):
        mock_usage.return_value = DiskUsage(
            total=100 * (1024 ** 3),
            used=95 * (1024 ** 3),
            free=5 * (1024 ** 3),
        )
        info = get_disk_info()
        assert info["free_gb"] < 10
        assert info["used_pct"] > 90


class TestEnsureDiskSpace:
    """Tests for ensure_disk_space."""

    @patch("disk_guard.get_disk_info")
    def test_sufficient_space_returns_true(self, mock_info):
        mock_info.return_value = {
            "total_gb": 100, "used_gb": 50,
            "free_gb": 50, "used_pct": 50,
        }
        assert ensure_disk_space(min_free_gb=10) is True

    @patch("disk_guard.cleanup_old_files")
    @patch("disk_guard.get_disk_info")
    def test_low_space_triggers_cleanup(self, mock_info, mock_cleanup):
        # First call: low space; second call (after cleanup): enough space
        mock_info.side_effect = [
            {"total_gb": 100, "used_gb": 95, "free_gb": 5, "used_pct": 95},
            {"total_gb": 100, "used_gb": 80, "free_gb": 20, "used_pct": 80},
        ]
        assert ensure_disk_space(min_free_gb=10) is True
        mock_cleanup.assert_called_once()

    @patch("disk_guard.cleanup_old_files")
    @patch("disk_guard.get_disk_info")
    def test_very_low_space_triggers_aggressive_cleanup(self, mock_info, mock_cleanup):
        # First: low, after normal cleanup: still low, after aggressive: OK
        mock_info.side_effect = [
            {"total_gb": 100, "used_gb": 98, "free_gb": 2, "used_pct": 98},
            {"total_gb": 100, "used_gb": 95, "free_gb": 5, "used_pct": 95},
            {"total_gb": 100, "used_gb": 85, "free_gb": 15, "used_pct": 85},
        ]
        assert ensure_disk_space(min_free_gb=10) is True
        assert mock_cleanup.call_count == 2
        # Second call should have max_age_hours=0 (aggressive)
        _, kwargs = mock_cleanup.call_args_list[1]
        assert kwargs.get("max_age_hours") == 0

    @patch("disk_guard.cleanup_old_files")
    @patch("disk_guard.get_disk_info")
    def test_insufficient_space_raises_error(self, mock_info, mock_cleanup):
        mock_info.return_value = {
            "total_gb": 100, "used_gb": 99, "free_gb": 1, "used_pct": 99,
        }
        with pytest.raises(RuntimeError, match="Insufficient disk space"):
            ensure_disk_space(min_free_gb=10)


class TestSafeRemoveFile:
    """Tests for _safe_remove_file."""

    def test_removes_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test data" * 100)
            path = f.name
        freed = _safe_remove_file(path)
        assert freed == 1  # Returns 1 on success
        assert not os.path.exists(path)

    def test_nonexistent_file_returns_zero(self):
        freed = _safe_remove_file("/tmp/nonexistent_test_file_xyz.txt")
        assert freed == 0


class TestSafeRemoveDir:
    """Tests for _safe_remove_dir."""

    def test_removes_existing_dir(self):
        tmpdir = tempfile.mkdtemp()
        # Create some files
        for i in range(3):
            with open(os.path.join(tmpdir, f"file_{i}.txt"), "w") as f:
                f.write("test" * 100)
        freed = _safe_remove_dir(tmpdir)
        assert freed == 1  # Returns 1 on success
        assert not os.path.exists(tmpdir)

    def test_nonexistent_dir_returns_zero(self):
        freed = _safe_remove_dir("/tmp/nonexistent_test_dir_xyz")
        assert freed == 0


class TestCleanupVideoFiles:
    """Tests for cleanup_video_files."""

    def test_cleanup_removes_video_dirs(self, tmp_path):
        """Test that cleanup removes frames, audio, cache dirs for a video."""
        vid = "test-video-123"
        # Create output/{video_id}/{subdir} structure
        output_dir = tmp_path / "output" / vid
        for subdir in ["frames", "audio", "audio_text", "cache"]:
            d = output_dir / subdir
            d.mkdir(parents=True, exist_ok=True)
            (d / "test.txt").write_text("test" * 100)

        # Create uploadedvideo/{video_id}.mp4
        upload_dir = tmp_path / "uploadedvideo"
        upload_dir.mkdir(exist_ok=True)
        (upload_dir / f"{vid}.mp4").write_text("video" * 1000)

        # Run cleanup from the tmp_path as working directory
        original_cwd = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            cleanup_video_files(vid)

            # Frames, audio, cache should be gone
            for subdir in ["frames", "audio", "audio_text", "cache"]:
                assert not (output_dir / subdir).exists()
            # Upload file should be gone
            assert not (upload_dir / f"{vid}.mp4").exists()
        finally:
            os.chdir(original_cwd)
