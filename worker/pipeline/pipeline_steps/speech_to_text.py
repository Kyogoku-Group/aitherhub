"""
Speech to Text
===============
Transcribes audio to text using OpenAI Whisper API.

Input (from context):
    - ctx.audio_path: Path to the extracted WAV audio file

Output (to context):
    - ctx.transcript: List of timestamped text segments
      [{"start": 0.1, "end": 2.5, "text": "この商品は"}, ...]

Strategy:
    1. Primary: OpenAI Whisper API (cloud, high accuracy)
    2. Fallback: Local whisper model via CLI (if API fails)
    3. Fallback: manus-speech-to-text utility

For long audio (>25MB), the file is split into chunks before
sending to the API, then results are merged.
"""
import os
import sys
import json
import logging
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from worker.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("worker.pipeline.speech_to_text")

# Whisper API has a 25MB file size limit
MAX_FILE_SIZE_MB = 25
CHUNK_DURATION_SECONDS = 600  # 10 min chunks for splitting


def _split_audio_into_chunks(audio_path: str, chunk_duration: int = CHUNK_DURATION_SECONDS) -> list[str]:
    """Split audio into chunks if it exceeds the API file size limit.

    Returns list of chunk file paths.
    """
    file_size_mb = Path(audio_path).stat().st_size / (1024 * 1024)
    if file_size_mb <= MAX_FILE_SIZE_MB:
        return [audio_path]

    logger.info(
        "[speech_to_text] Audio too large (%.1fMB), splitting into %ds chunks",
        file_size_mb, chunk_duration,
    )

    audio_dir = Path(audio_path).parent
    chunk_pattern = str(audio_dir / "audio_chunk_%03d.wav")

    cmd = [
        "ffmpeg", "-y",
        "-i", audio_path,
        "-f", "segment",
        "-segment_time", str(chunk_duration),
        "-c", "copy",
        chunk_pattern,
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        logger.error("[speech_to_text] Failed to split audio: %s", e)
        return [audio_path]

    chunks = sorted(audio_dir.glob("audio_chunk_*.wav"))
    chunk_paths = [str(c) for c in chunks]
    logger.info("[speech_to_text] Split into %d chunks", len(chunk_paths))
    return chunk_paths


def _transcribe_with_openai_api(audio_path: str, language: str = "ja") -> list[dict]:
    """Transcribe audio using OpenAI Whisper API.

    Returns list of segments: [{"start": float, "end": float, "text": str}, ...]
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("[speech_to_text] openai package not available")
        return []

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("[speech_to_text] OPENAI_API_KEY not set")
        return []

    try:
        client = OpenAI()

        with open(audio_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        segments = []
        if hasattr(response, "segments") and response.segments:
            for seg in response.segments:
                segments.append({
                    "start": round(seg.get("start", seg.get("start", 0.0)), 3),
                    "end": round(seg.get("end", seg.get("end", 0.0)), 3),
                    "text": seg.get("text", "").strip(),
                    "confidence": seg.get("avg_logprob", 0.0),
                })
        elif hasattr(response, "text") and response.text:
            # Fallback: no segment-level timestamps
            segments.append({
                "start": 0.0,
                "end": 0.0,
                "text": response.text.strip(),
                "confidence": 0.0,
            })

        return segments

    except Exception as e:
        logger.error("[speech_to_text] OpenAI API error: %s", e)
        return []


def _transcribe_with_manus_cli(audio_path: str) -> list[dict]:
    """Fallback: Use manus-speech-to-text CLI utility."""
    try:
        result = subprocess.run(
            ["manus-speech-to-text", audio_path],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout.strip()
            return [{"start": 0.0, "end": 0.0, "text": text, "confidence": 0.0}]
    except Exception as e:
        logger.warning("[speech_to_text] manus-speech-to-text failed: %s", e)
    return []


def _transcribe_audio(audio_path: str, language: str = "ja") -> list[dict]:
    """Transcribe audio with fallback chain.

    1. OpenAI Whisper API (chunked if needed)
    2. manus-speech-to-text CLI
    """
    chunks = _split_audio_into_chunks(audio_path)

    all_segments = []
    time_offset = 0.0

    for chunk_path in chunks:
        segments = _transcribe_with_openai_api(chunk_path, language)

        if not segments:
            # Fallback
            segments = _transcribe_with_manus_cli(chunk_path)

        # Apply time offset for chunked audio
        if time_offset > 0:
            for seg in segments:
                seg["start"] = round(seg["start"] + time_offset, 3)
                seg["end"] = round(seg["end"] + time_offset, 3)

        all_segments.extend(segments)

        # Calculate offset for next chunk
        if segments:
            time_offset = max(seg["end"] for seg in segments) if segments[-1]["end"] > 0 else time_offset + CHUNK_DURATION_SECONDS
        else:
            time_offset += CHUNK_DURATION_SECONDS

    return all_segments


def run_speech_to_text(ctx: PipelineContext) -> PipelineContext:
    """Pipeline step: Transcribe audio to text.

    Saves results to both ctx.transcript and the database.
    """
    audio_path = ctx.audio_path
    if not audio_path or not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    transcript = _transcribe_audio(audio_path)

    if not transcript:
        logger.warning("[speech_to_text] No transcript generated for video %s", ctx.video_id)
        ctx.transcript = []
        return ctx

    ctx.transcript = transcript
    total_text_len = sum(len(seg.get("text", "")) for seg in transcript)
    logger.info(
        "[speech_to_text] Transcribed %d segments (%d chars) for video %s",
        len(transcript), total_text_len, ctx.video_id,
    )

    # Save to DB
    try:
        from worker.pipeline.pipeline_db import save_transcripts
        save_transcripts(ctx.video_id, transcript)
    except Exception as e:
        logger.warning("[speech_to_text] DB save failed (non-critical): %s", e)

    return ctx
