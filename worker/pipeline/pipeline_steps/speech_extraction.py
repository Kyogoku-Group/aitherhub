"""
Speech Extraction
==================
Extracts audio track from video using FFmpeg.

Input (from context):
    - ctx.video_path: Path to the source video file

Output (to context):
    - ctx.audio_path: Path to the extracted WAV audio file

The audio is extracted as 16kHz mono WAV, which is the optimal
format for Whisper and most speech-to-text engines.
"""
import sys
import logging
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from worker.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("worker.pipeline.speech_extraction")

# FFmpeg settings for speech-to-text optimized audio
SAMPLE_RATE = 16000
CHANNELS = 1
AUDIO_FORMAT = "wav"


def _extract_audio(video_path: str, output_path: str) -> bool:
    """Extract audio from video using FFmpeg.

    Outputs 16kHz mono WAV for optimal Whisper compatibility.

    Args:
        video_path: Path to source video.
        output_path: Path for output WAV file.

    Returns:
        True if extraction succeeded.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",                          # No video
        "-acodec", "pcm_s16le",         # PCM 16-bit
        "-ar", str(SAMPLE_RATE),        # 16kHz
        "-ac", str(CHANNELS),           # Mono
        output_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout
        )
        if result.returncode != 0:
            logger.error(
                "[speech_extraction] FFmpeg failed (exit=%d): %s",
                result.returncode, result.stderr[-500:] if result.stderr else "",
            )
            return False

        output = Path(output_path)
        if not output.exists() or output.stat().st_size == 0:
            logger.error("[speech_extraction] Output file is empty or missing")
            return False

        size_mb = output.stat().st_size / (1024 * 1024)
        logger.info(
            "[speech_extraction] Audio extracted: %.1f MB (%dHz, %dch)",
            size_mb, SAMPLE_RATE, CHANNELS,
        )
        return True

    except subprocess.TimeoutExpired:
        logger.error("[speech_extraction] FFmpeg timed out (600s)")
        return False
    except Exception as e:
        logger.error("[speech_extraction] FFmpeg error: %s", e)
        return False


def run_speech_extraction(ctx: PipelineContext) -> PipelineContext:
    """Pipeline step: Extract audio from video.

    Creates a WAV file alongside the video file:
        /tmp/aitherhub/{video_id}/audio.wav
    """
    video_path = ctx.video_path
    if not video_path or not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Output audio path: same directory as video
    video_dir = Path(video_path).parent
    audio_path = str(video_dir / "audio.wav")

    success = _extract_audio(video_path, audio_path)
    if not success:
        raise RuntimeError(f"Audio extraction failed for video {ctx.video_id}")

    ctx.audio_path = audio_path
    logger.info(
        "[speech_extraction] Audio ready: %s (video=%s)",
        audio_path, ctx.video_id,
    )

    return ctx
