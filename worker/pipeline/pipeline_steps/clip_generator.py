"""
Clip Generator
===============
Generates vertical clips from detected sales moments.

Input (from context):
    - ctx.video_path: Path to the source video file
    - ctx.sales_moments: Detected sales moments with start/end times
    - ctx.video_id: Video identifier

Output (to context):
    - ctx.clips: Generated clip metadata
      [{"clip_id": str, "start": float, "end": float, "output_path": str, "status": str}, ...]

Each sales moment is trimmed from the source video using FFmpeg,
cropped to 9:16 vertical format, and saved to a temp directory.
Upload to blob storage is handled separately.
"""
import os
import sys
import uuid
import logging
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from worker.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("worker.pipeline.clip_generator")

# Clip generation settings
CLIP_PADDING_BEFORE = 2.0   # Seconds of padding before the moment
CLIP_PADDING_AFTER = 3.0    # Seconds of padding after the moment
MIN_CLIP_DURATION = 5.0     # Minimum clip duration in seconds
MAX_CLIP_DURATION = 60.0    # Maximum clip duration in seconds
MAX_CLIPS = 5               # Maximum number of clips to generate per video

# FFmpeg encoding settings for vertical clips
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
VIDEO_BITRATE = "4M"
AUDIO_BITRATE = "128k"
CRF = 23


def _get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Get video width and height using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "stream=width,height",
            "-select_streams", "v:0",
            "-of", "json",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        import json
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        return int(stream.get("width", 1920)), int(stream.get("height", 1080))
    except Exception:
        return 1920, 1080


def _build_crop_filter(src_width: int, src_height: int) -> str:
    """Build FFmpeg crop filter for 9:16 vertical output.

    Strategy:
        - If source is already vertical (9:16), no crop needed
        - If source is horizontal (16:9), crop center to 9:16
        - Scale to 1080x1920 output
    """
    src_ratio = src_width / src_height if src_height > 0 else 1.78
    target_ratio = 9 / 16  # 0.5625

    if src_ratio <= target_ratio + 0.05:
        # Already vertical or close — just scale
        return f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2"
    else:
        # Horizontal source — crop center to 9:16 ratio
        crop_width = int(src_height * target_ratio)
        crop_x = (src_width - crop_width) // 2
        return (
            f"crop={crop_width}:{src_height}:{crop_x}:0,"
            f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
        )


def _generate_clip(
    video_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
    crop_filter: str,
) -> bool:
    """Generate a single clip using FFmpeg.

    Args:
        video_path: Source video path.
        output_path: Output clip path.
        start_time: Clip start time in seconds.
        end_time: Clip end time in seconds.
        crop_filter: FFmpeg video filter string.

    Returns:
        True if generation succeeded.
    """
    duration = end_time - start_time

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-vf", crop_filter,
        "-c:v", "libx264",
        "-crf", str(CRF),
        "-preset", "medium",
        "-b:v", VIDEO_BITRATE,
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
        output_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min per clip
        )

        if result.returncode != 0:
            logger.error(
                "[clip_generator] FFmpeg failed (exit=%d): %s",
                result.returncode, result.stderr[-300:] if result.stderr else "",
            )
            return False

        output = Path(output_path)
        if not output.exists() or output.stat().st_size == 0:
            logger.error("[clip_generator] Output file is empty or missing")
            return False

        size_mb = output.stat().st_size / (1024 * 1024)
        logger.info(
            "[clip_generator] Clip generated: %.1fMB, %.1fs",
            size_mb, duration,
        )
        return True

    except subprocess.TimeoutExpired:
        logger.error("[clip_generator] FFmpeg timed out")
        return False
    except Exception as e:
        logger.error("[clip_generator] Error: %s", e)
        return False


def run_clip_generation(ctx: PipelineContext) -> PipelineContext:
    """Pipeline step: Generate vertical clips from sales moments.

    For each sales moment (up to MAX_CLIPS), generates a vertical
    clip trimmed from the source video.
    """
    if not ctx.sales_moments:
        logger.info("[clip_generator] No sales moments for video %s", ctx.video_id)
        ctx.clips = []
        return ctx

    video_path = ctx.video_path
    if not video_path or not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Get video dimensions for crop filter
    src_width, src_height = _get_video_dimensions(video_path)
    crop_filter = _build_crop_filter(src_width, src_height)
    logger.info(
        "[clip_generator] Source: %dx%d, crop_filter: %s",
        src_width, src_height, crop_filter,
    )

    # Sort sales moments by score (best first)
    moments = sorted(ctx.sales_moments, key=lambda x: x.get("score", 0), reverse=True)
    moments = moments[:MAX_CLIPS]

    # Output directory
    output_dir = Path(video_path).parent / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)

    clips = []
    for i, moment in enumerate(moments):
        clip_id = str(uuid.uuid4())[:8]
        start = max(0, moment["start"] - CLIP_PADDING_BEFORE)
        end = moment["end"] + CLIP_PADDING_AFTER

        # Enforce duration limits
        duration = end - start
        if duration < MIN_CLIP_DURATION:
            # Extend symmetrically
            pad = (MIN_CLIP_DURATION - duration) / 2
            start = max(0, start - pad)
            end = end + pad
        elif duration > MAX_CLIP_DURATION:
            end = start + MAX_CLIP_DURATION

        output_path = str(output_dir / f"clip_{clip_id}.mp4")

        logger.info(
            "[clip_generator] Generating clip %d/%d: %s (%.1fs-%.1fs, score=%.3f)",
            i + 1, len(moments), clip_id, start, end, moment.get("score", 0),
        )

        success = _generate_clip(video_path, output_path, start, end, crop_filter)

        clip_info = {
            "clip_id": clip_id,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "score": moment.get("score", 0),
            "reason": moment.get("reason", ""),
            "output_path": output_path if success else "",
            "status": "generated" if success else "failed",
        }
        clips.append(clip_info)

    ctx.clips = clips

    generated = sum(1 for c in clips if c["status"] == "generated")
    logger.info(
        "[clip_generator] Generated %d/%d clips for video %s",
        generated, len(clips), ctx.video_id,
    )

    return ctx
