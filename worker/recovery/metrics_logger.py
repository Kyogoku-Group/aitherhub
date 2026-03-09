"""
Worker Metrics Logger
======================
Structured logging for clip/video processing performance metrics.

Captures:
    - download_time: Time to download source video from blob
    - encode_time: Time for ffmpeg encoding
    - upload_time: Time to upload clip to blob
    - total_processing_time: Wall-clock time for entire job
    - video_size: Size of source video in bytes
    - clip_length: Duration of output clip in seconds

Usage:
    metrics = JobMetrics(job_id="clip-123", job_type="generate_clip")
    metrics.start()

    metrics.start_phase("download")
    # ... download ...
    metrics.end_phase("download", video_size=850_000_000)

    metrics.start_phase("encode")
    # ... encode ...
    metrics.end_phase("encode", clip_length=15.0)

    metrics.start_phase("upload")
    # ... upload ...
    metrics.end_phase("upload")

    metrics.finish(status="completed")
    # Automatically logs structured metrics
"""
import os
import sys
import time
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("worker.metrics")

# Ensure structured logging format
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(name)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class JobMetrics:
    """Collects and logs performance metrics for a single job."""

    def __init__(self, job_id: str, job_type: str = "generate_clip"):
        self.job_id = job_id
        self.job_type = job_type
        self._start_time: float = 0.0
        self._end_time: float = 0.0
        self._phases: dict = {}
        self._current_phase: Optional[str] = None
        self._metadata: dict = {}

    def start(self):
        """Mark the start of job processing."""
        self._start_time = time.time()
        logger.info(
            "worker.metrics.job_started job_id=%s job_type=%s",
            self.job_id, self.job_type,
        )

    def start_phase(self, phase_name: str):
        """Mark the start of a processing phase."""
        self._current_phase = phase_name
        self._phases[phase_name] = {
            "start": time.time(),
            "end": None,
            "duration_s": None,
            "metadata": {},
        }

    def end_phase(self, phase_name: str, **metadata):
        """Mark the end of a processing phase with optional metadata.

        Keyword args are stored as phase metadata:
            video_size=850_000_000
            clip_length=15.0
            output_size=12_000_000
        """
        if phase_name not in self._phases:
            return

        end_time = time.time()
        phase = self._phases[phase_name]
        phase["end"] = end_time
        phase["duration_s"] = round(end_time - phase["start"], 2)
        phase["metadata"] = metadata

        # Store key metadata at top level too
        self._metadata.update(metadata)

        logger.info(
            "worker.metrics.phase_completed job_id=%s phase=%s duration=%.2fs %s",
            self.job_id,
            phase_name,
            phase["duration_s"],
            " ".join(f"{k}={v}" for k, v in metadata.items()),
        )

    def set_metadata(self, **kwargs):
        """Set additional metadata for the job."""
        self._metadata.update(kwargs)

    def finish(self, status: str = "completed"):
        """Mark the job as finished and emit the final metrics log."""
        self._end_time = time.time()
        total_time = round(self._end_time - self._start_time, 2) if self._start_time else 0.0

        metrics = {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": status,
            "total_processing_time_s": total_time,
        }

        # Add phase durations
        for phase_name, phase_data in self._phases.items():
            key = f"{phase_name}_time_s"
            metrics[key] = phase_data.get("duration_s", 0.0)

        # Add metadata
        if "video_size" in self._metadata:
            video_size = self._metadata["video_size"]
            metrics["video_size_bytes"] = video_size
            metrics["video_size_mb"] = round(video_size / (1024 * 1024), 1)

        if "clip_length" in self._metadata:
            metrics["clip_length_s"] = self._metadata["clip_length"]

        if "output_size" in self._metadata:
            metrics["output_size_bytes"] = self._metadata["output_size"]
            metrics["output_size_mb"] = round(
                self._metadata["output_size"] / (1024 * 1024), 1
            )

        # Emit structured log
        logger.info(
            "worker.metrics.clip_processing %s",
            json.dumps(metrics, ensure_ascii=False),
        )

        return metrics

    def to_dict(self) -> dict:
        """Return all collected metrics as a dictionary."""
        total_time = (
            round(self._end_time - self._start_time, 2)
            if self._end_time
            else round(time.time() - self._start_time, 2)
            if self._start_time
            else 0.0
        )
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "total_processing_time_s": total_time,
            "phases": {
                name: {
                    "duration_s": data.get("duration_s"),
                    **data.get("metadata", {}),
                }
                for name, data in self._phases.items()
            },
            "metadata": self._metadata,
        }
