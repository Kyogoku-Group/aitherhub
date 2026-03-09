"""
Scene Detection
================
Detects scene boundaries in a video using PySceneDetect.

Input (from context):
    - ctx.video_path: Path to the source video file

Output (to context):
    - ctx.scenes: List of scene boundaries
      [{"start": 0.0, "end": 4.3, "scene_index": 0}, ...]

Fallback:
    If PySceneDetect is not available, falls back to FFmpeg-based
    scene change detection using the 'select' filter.
"""
import sys
import json
import logging
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from worker.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("worker.pipeline.scene_detection")


def _get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "json",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception as e:
        logger.warning("[scene_detection] Could not get duration: %s", e)
        return 0.0


def _detect_scenes_pyscenedetect(video_path: str) -> list[dict]:
    """Detect scenes using PySceneDetect library."""
    try:
        from scenedetect import detect, ContentDetector
    except ImportError:
        logger.info("[scene_detection] PySceneDetect not available, using ffmpeg fallback")
        return _detect_scenes_ffmpeg(video_path)

    try:
        scene_list = detect(video_path, ContentDetector(threshold=27.0))

        scenes = []
        for i, (start, end) in enumerate(scene_list):
            scenes.append({
                "start": round(start.get_seconds(), 3),
                "end": round(end.get_seconds(), 3),
                "scene_index": i,
            })

        return scenes

    except Exception as e:
        logger.warning("[scene_detection] PySceneDetect failed: %s, trying ffmpeg", e)
        return _detect_scenes_ffmpeg(video_path)


def _detect_scenes_ffmpeg(video_path: str) -> list[dict]:
    """Fallback scene detection using FFmpeg scene change filter.

    Uses the 'select' filter with scene change detection threshold.
    Returns approximate scene boundaries based on detected keyframe changes.
    """
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_frames",
            "-select_streams", "v:0",
            "-show_entries", "frame=pts_time,pict_type",
            "-of", "json",
            video_path,
        ]
        # This can be slow for long videos; use scene filter instead
        cmd = [
            "ffmpeg", "-i", video_path,
            "-filter:v", "select='gt(scene,0.3)',showinfo",
            "-f", "null", "-",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )

        # Parse showinfo output for timestamps
        import re
        timestamps = [0.0]
        for line in result.stderr.split("\n"):
            match = re.search(r"pts_time:(\d+\.?\d*)", line)
            if match:
                timestamps.append(float(match.group(1)))

        # Get video duration for the last scene
        duration = _get_video_duration(video_path)
        if duration > 0 and (not timestamps or timestamps[-1] < duration):
            timestamps.append(duration)

        # Build scene list from timestamps
        scenes = []
        for i in range(len(timestamps) - 1):
            scenes.append({
                "start": round(timestamps[i], 3),
                "end": round(timestamps[i + 1], 3),
                "scene_index": i,
            })

        return scenes

    except Exception as e:
        logger.error("[scene_detection] FFmpeg fallback also failed: %s", e)
        return []


def run_scene_detection(ctx: PipelineContext) -> PipelineContext:
    """Pipeline step: Detect scene boundaries in the video.

    Saves results to both ctx.scenes and the database.
    """
    video_path = ctx.video_path
    if not video_path or not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Get video duration
    duration = _get_video_duration(video_path)
    if duration > 0:
        ctx.video_duration = duration

    # Detect scenes
    scenes = _detect_scenes_pyscenedetect(video_path)

    if not scenes and duration > 0:
        # If no scenes detected, treat entire video as one scene
        scenes = [{"start": 0.0, "end": duration, "scene_index": 0}]
        logger.info("[scene_detection] No scene changes detected; using single scene")

    ctx.scenes = scenes
    logger.info(
        "[scene_detection] Detected %d scenes for video %s (duration=%.1fs)",
        len(scenes), ctx.video_id, duration,
    )

    # Save to DB
    try:
        from worker.pipeline.pipeline_db import save_scenes
        save_scenes(ctx.video_id, scenes)
    except Exception as e:
        logger.warning("[scene_detection] DB save failed (non-critical): %s", e)

    return ctx
