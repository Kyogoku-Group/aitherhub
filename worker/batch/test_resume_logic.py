#!/usr/bin/env python3
"""
Integration tests for process_video.py resume logic.

Verifies that STEP_ORDER indices and start_step conditions are consistent.

Usage:
    python test_resume_logic.py
"""
import os
import sys
import re
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from video_status import VideoStatus


# Reconstruct STEP_ORDER as defined in process_video.py
STEP_ORDER = [
    VideoStatus.STEP_0_EXTRACT_FRAMES,
    VideoStatus.STEP_1_DETECT_PHASES,
    VideoStatus.STEP_2_EXTRACT_METRICS,
    VideoStatus.STEP_3_TRANSCRIBE_AUDIO,
    VideoStatus.STEP_4_IMAGE_CAPTION,
    VideoStatus.STEP_5_BUILD_PHASE_UNITS,
    VideoStatus.STEP_6_BUILD_PHASE_DESCRIPTION,
    VideoStatus.STEP_7_GROUPING,
    VideoStatus.STEP_8_UPDATE_BEST_PHASE,
    VideoStatus.STEP_9_BUILD_VIDEO_STRUCTURE_FEATURES,
    VideoStatus.STEP_10_ASSIGN_VIDEO_STRUCTURE_GROUP,
    VideoStatus.STEP_11_UPDATE_VIDEO_STRUCTURE_GROUP_STATS,
    VideoStatus.STEP_12_UPDATE_VIDEO_STRUCTURE_BEST,
    VideoStatus.STEP_12_5_PRODUCT_DETECTION,
    VideoStatus.STEP_13_BUILD_REPORTS,
    VideoStatus.STEP_14_FINALIZE,
]


def status_to_step_index(status):
    """Mirror of the function in process_video.py."""
    if not status:
        return 0
    if status == VideoStatus.DONE:
        return len(STEP_ORDER)
    if status in STEP_ORDER:
        return STEP_ORDER.index(status)
    return 0


class TestStepOrderIndices(unittest.TestCase):
    """Verify STEP_ORDER indices are correct."""

    def test_extract_frames_at_index_0(self):
        self.assertEqual(STEP_ORDER.index(VideoStatus.STEP_0_EXTRACT_FRAMES), 0)

    def test_detect_phases_at_index_1(self):
        self.assertEqual(STEP_ORDER.index(VideoStatus.STEP_1_DETECT_PHASES), 1)

    def test_extract_metrics_at_index_2(self):
        self.assertEqual(STEP_ORDER.index(VideoStatus.STEP_2_EXTRACT_METRICS), 2)

    def test_transcribe_audio_at_index_3(self):
        self.assertEqual(STEP_ORDER.index(VideoStatus.STEP_3_TRANSCRIBE_AUDIO), 3)

    def test_image_caption_at_index_4(self):
        self.assertEqual(STEP_ORDER.index(VideoStatus.STEP_4_IMAGE_CAPTION), 4)

    def test_build_phase_units_at_index_5(self):
        self.assertEqual(STEP_ORDER.index(VideoStatus.STEP_5_BUILD_PHASE_UNITS), 5)

    def test_build_phase_description_at_index_6(self):
        self.assertEqual(STEP_ORDER.index(VideoStatus.STEP_6_BUILD_PHASE_DESCRIPTION), 6)

    def test_grouping_at_index_7(self):
        self.assertEqual(STEP_ORDER.index(VideoStatus.STEP_7_GROUPING), 7)

    def test_product_detection_at_index_13(self):
        self.assertEqual(STEP_ORDER.index(VideoStatus.STEP_12_5_PRODUCT_DETECTION), 13)

    def test_total_steps(self):
        self.assertEqual(len(STEP_ORDER), 16)


class TestStatusToStepIndex(unittest.TestCase):
    """Verify status_to_step_index returns correct indices."""

    def test_none_returns_0(self):
        self.assertEqual(status_to_step_index(None), 0)

    def test_empty_returns_0(self):
        self.assertEqual(status_to_step_index(""), 0)

    def test_unknown_status_returns_0(self):
        self.assertEqual(status_to_step_index("UNKNOWN_STATUS"), 0)

    def test_extract_frames_returns_0(self):
        self.assertEqual(status_to_step_index(VideoStatus.STEP_0_EXTRACT_FRAMES), 0)

    def test_grouping_returns_7(self):
        self.assertEqual(status_to_step_index(VideoStatus.STEP_7_GROUPING), 7)

    def test_done_returns_len(self):
        self.assertEqual(status_to_step_index(VideoStatus.DONE), len(STEP_ORDER))


class TestResumeLogic(unittest.TestCase):
    """Verify resume logic works correctly with STEP_ORDER."""

    def _simulate_resume(self, current_status):
        """Simulate the resume logic from process_video.py main().

        The actual code resumes from any step > 0, and fires split_async
        if start_step >= 7.
        """
        raw_start_step = status_to_step_index(current_status)

        if raw_start_step > 0:
            start_step = raw_start_step
            resumed = True
        else:
            start_step = 0
            resumed = False

        return start_step, resumed

    def test_new_video_starts_from_0(self):
        """New video (no status) should start from step 0."""
        start_step, resumed = self._simulate_resume(None)
        self.assertEqual(start_step, 0)
        self.assertFalse(resumed)

    def test_uploaded_starts_from_0(self):
        """Uploaded video should start from step 0."""
        start_step, resumed = self._simulate_resume("uploaded")
        self.assertEqual(start_step, 0)
        self.assertFalse(resumed)

    def test_extract_frames_starts_from_0(self):
        """Video at STEP_0 (index 0) should start from 0 (raw_start_step=0, not > 0)."""
        start_step, resumed = self._simulate_resume(VideoStatus.STEP_0_EXTRACT_FRAMES)
        self.assertEqual(start_step, 0)
        self.assertFalse(resumed)

    def test_detect_phases_resumes(self):
        """Video at STEP_1 (index 1) should resume."""
        start_step, resumed = self._simulate_resume(VideoStatus.STEP_1_DETECT_PHASES)
        self.assertEqual(start_step, 1)
        self.assertTrue(resumed)

    def test_step5_resumes(self):
        """Video at STEP_5 (index 5) should resume."""
        start_step, resumed = self._simulate_resume(VideoStatus.STEP_5_BUILD_PHASE_UNITS)
        self.assertEqual(start_step, 5)
        self.assertTrue(resumed)

    def test_step7_resumes(self):
        """Video at STEP_7 GROUPING (index 7) should resume."""
        start_step, resumed = self._simulate_resume(VideoStatus.STEP_7_GROUPING)
        self.assertEqual(start_step, 7)
        self.assertTrue(resumed)

    def test_step8_resumes(self):
        """Video at STEP_8 (index 8) should resume."""
        start_step, resumed = self._simulate_resume(VideoStatus.STEP_8_UPDATE_BEST_PHASE)
        self.assertEqual(start_step, 8)
        self.assertTrue(resumed)

    def test_step13_resumes(self):
        """Video at STEP_13 (index 14) should resume."""
        start_step, resumed = self._simulate_resume(VideoStatus.STEP_13_BUILD_REPORTS)
        self.assertEqual(start_step, 14)
        self.assertTrue(resumed)


class TestStartStepConditions(unittest.TestCase):
    """
    Verify key structural properties of start_step conditions in process_video.py.

    Note: The actual code uses complex step conditions due to parallel execution
    (e.g., STEP 0+3 run in parallel), so we only test key structural properties
    rather than exact sequential ordering.
    """

    def setUp(self):
        """Read process_video.py source."""
        script_path = os.path.join(os.path.dirname(__file__), "process_video.py")
        with open(script_path, "r") as f:
            self.source = f.read()

    def test_has_start_step_conditions(self):
        """Source should contain start_step conditions."""
        conditions = re.findall(r'if start_step <= (\d+):', self.source)
        self.assertGreater(len(conditions), 10,
            f"Expected at least 10 start_step conditions, got {len(conditions)}")

    def test_max_condition_matches_last_step(self):
        """Highest start_step condition should correspond to the last step."""
        conditions = re.findall(r'if start_step <= (\d+):', self.source)
        max_cond = max(int(c) for c in conditions)
        # Should be len(STEP_ORDER) - 1 = 15
        self.assertEqual(max_cond, len(STEP_ORDER) - 1,
            f"Max condition should be {len(STEP_ORDER) - 1}, got {max_cond}")

    def test_resume_threshold(self):
        """Resume threshold should be > 0 (any step > 0 resumes)."""
        match = re.search(r'if raw_start_step > (\d+):', self.source)
        self.assertIsNotNone(match, "Resume threshold not found")
        threshold = int(match.group(1))
        self.assertEqual(threshold, 0,
            f"Resume threshold should be > 0, got > {threshold}")

    def test_split_async_threshold(self):
        """Split async should fire when start_step >= 7 (STEP_7_GROUPING)."""
        match = re.search(r'if start_step >= (\d+):\s*\n\s*fire_split_async', self.source)
        self.assertIsNotNone(match, "Split async threshold not found")
        threshold = int(match.group(1))
        self.assertEqual(threshold, 7,
            f"Split async threshold should be 7, got {threshold}")


class TestVideoProgressConsistency(unittest.TestCase):
    """Verify video_progress.py has entries for all steps."""

    def test_progress_has_step_entries(self):
        """video_progress.py should have entries for key steps."""
        progress_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "backend", "app", "utils", "video_progress.py"
        )
        if not os.path.exists(progress_path):
            self.skipTest("video_progress.py not found at expected path")

        with open(progress_path, "r") as f:
            content = f.read()

        self.assertIn("STEP_0_EXTRACT_FRAMES", content)
        self.assertIn("STEP_7_GROUPING", content)
        self.assertIn("STEP_14_FINALIZE", content)


if __name__ == "__main__":
    print("=" * 60)
    print("process_video.py Resume Logic Tests")
    print("=" * 60)
    print(f"STEP_ORDER length: {len(STEP_ORDER)}")
    for i, step in enumerate(STEP_ORDER):
        print(f"  [{i:2d}] {step}")
    print()

    unittest.main(verbosity=2)
