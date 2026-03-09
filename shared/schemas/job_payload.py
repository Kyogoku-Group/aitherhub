"""
Job Payload Schemas
===================
Type definitions for queue job payloads.
Ensures API (producer) and Worker (consumer) agree on message format.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional
import json


@dataclass
class VideoAnalysisJob:
    """Payload for video analysis pipeline job."""
    video_id: str
    blob_url: str
    job_type: str = "video_analysis"
    email: str = ""
    user_id: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "VideoAnalysisJob":
        return cls(
            video_id=data.get("video_id", ""),
            blob_url=data.get("blob_url", ""),
            job_type=data.get("job_type", "video_analysis"),
            email=data.get("email", ""),
            user_id=str(data.get("user_id", "")),
        )


@dataclass
class ClipGenerationJob:
    """Payload for clip generation job."""
    clip_id: str
    video_id: str
    blob_url: str
    time_start: float
    time_end: float
    job_type: str = "generate_clip"
    phase_index: int = -1
    speed_factor: float = 1.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "ClipGenerationJob":
        return cls(
            clip_id=data.get("clip_id", ""),
            video_id=data.get("video_id", ""),
            blob_url=data.get("blob_url", ""),
            time_start=float(data.get("time_start", 0)),
            time_end=float(data.get("time_end", 0)),
            phase_index=int(data.get("phase_index", -1)),
            speed_factor=float(data.get("speed_factor", 1.0)),
        )


@dataclass
class LiveCaptureJob:
    """Payload for TikTok live stream capture job."""
    video_id: str
    live_url: str
    job_type: str = "live_capture"
    email: str = ""
    user_id: str = ""
    duration: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "LiveCaptureJob":
        return cls(
            video_id=data.get("video_id", ""),
            live_url=data.get("live_url", ""),
            email=data.get("email", ""),
            user_id=str(data.get("user_id", "")),
            duration=int(data.get("duration", 0)),
        )


@dataclass
class LiveMonitorJob:
    """Payload for TikTok live monitoring job."""
    video_id: str
    username: str
    job_type: str = "live_monitor"
    live_url: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "LiveMonitorJob":
        return cls(
            video_id=data.get("video_id", ""),
            username=data.get("username", ""),
            live_url=data.get("live_url", ""),
        )


def parse_job_payload(data: dict):
    """Parse a raw job payload dict into the appropriate typed job object."""
    job_type = data.get("job_type", "video_analysis")
    if job_type == "generate_clip":
        return ClipGenerationJob.from_dict(data)
    elif job_type == "live_capture":
        return LiveCaptureJob.from_dict(data)
    elif job_type == "live_monitor":
        return LiveMonitorJob.from_dict(data)
    else:
        return VideoAnalysisJob.from_dict(data)
