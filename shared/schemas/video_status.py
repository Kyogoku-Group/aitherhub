"""
Video Processing Status
=======================
Single source of truth for video processing pipeline statuses.
Used by both API (to read/display) and Worker (to update).
"""


class VideoStatus:
    """Video processing pipeline status constants."""

    NEW = "NEW"

    # === PRE-PROCESSING ===
    STEP_COMPRESS_1080P = "STEP_COMPRESS_1080P"

    # === PIPELINE CORE ===
    STEP_0_EXTRACT_FRAMES = "STEP_0_EXTRACT_FRAMES"
    STEP_1_DETECT_PHASES = "STEP_1_DETECT_PHASES"
    STEP_2_EXTRACT_METRICS = "STEP_2_EXTRACT_METRICS"
    STEP_3_TRANSCRIBE_AUDIO = "STEP_3_TRANSCRIBE_AUDIO"
    STEP_4_IMAGE_CAPTION = "STEP_4_IMAGE_CAPTION"
    STEP_5_BUILD_PHASE_UNITS = "STEP_5_BUILD_PHASE_UNITS"
    STEP_6_BUILD_PHASE_DESCRIPTION = "STEP_6_BUILD_PHASE_DESCRIPTION"

    # === PHASE LEVEL ===
    STEP_7_GROUPING = "STEP_7_GROUPING"
    STEP_8_UPDATE_BEST_PHASE = "STEP_8_UPDATE_BEST_PHASE"

    # === VIDEO STRUCTURE LEVEL ===
    STEP_9_BUILD_VIDEO_STRUCTURE_FEATURES = "STEP_9_BUILD_VIDEO_STRUCTURE_FEATURES"
    STEP_10_ASSIGN_VIDEO_STRUCTURE_GROUP = "STEP_10_ASSIGN_VIDEO_STRUCTURE_GROUP"
    STEP_11_UPDATE_VIDEO_STRUCTURE_GROUP_STATS = "STEP_11_UPDATE_VIDEO_STRUCTURE_GROUP_STATS"
    STEP_12_UPDATE_VIDEO_STRUCTURE_BEST = "STEP_12_UPDATE_VIDEO_STRUCTURE_BEST"

    # === PRODUCT DETECTION ===
    STEP_12_5_PRODUCT_DETECTION = "STEP_12_5_PRODUCT_DETECTION"

    # === FINAL ===
    STEP_13_BUILD_REPORTS = "STEP_13_BUILD_REPORTS"
    STEP_14_FINALIZE = "STEP_14_FINALIZE"

    # === TERMINAL ===
    DONE = "DONE"
    ERROR = "ERROR"

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        """Check if a status is terminal (no further processing)."""
        return status in (cls.DONE, cls.ERROR)

    @classmethod
    def is_processing(cls, status: str) -> bool:
        """Check if a status indicates active processing."""
        return status.startswith("STEP_")


class ClipStatus:
    """Clip generation status constants."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD = "dead"

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        return status in (cls.COMPLETED, cls.DEAD)

    @classmethod
    def is_active(cls, status: str) -> bool:
        return status in (cls.DOWNLOADING, cls.PROCESSING, cls.UPLOADING)
