"""
Transcript Segmentation
========================
Segments raw transcript into semantically meaningful blocks.

Input (from context):
    - ctx.transcript: Raw speech-to-text segments
    - ctx.scenes: Scene boundaries (optional, used for alignment)

Output (to context):
    - ctx.segments: Semantically grouped transcript blocks
      [{"start": 0, "end": 4, "text": "...", "segment_index": 0, "topic": ""}, ...]

Strategy:
    1. Merge short consecutive transcript segments into longer blocks
    2. Split at natural boundaries (pauses, scene changes)
    3. Optionally use LLM to identify topic boundaries

For v1, we use a rule-based approach:
    - Merge segments with gaps < 1.5s
    - Split at scene boundaries
    - Minimum segment duration: 3s
    - Maximum segment duration: 30s
"""
import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from worker.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("worker.pipeline.transcript_segmentation")

# Segmentation parameters
MERGE_GAP_THRESHOLD = 1.5    # Merge segments with gaps < this (seconds)
MIN_SEGMENT_DURATION = 3.0   # Minimum segment duration (seconds)
MAX_SEGMENT_DURATION = 30.0  # Maximum segment duration (seconds)
SCENE_BOUNDARY_WEIGHT = 0.8  # How strongly scene boundaries influence splits


def _get_scene_boundaries(scenes: list[dict]) -> list[float]:
    """Extract scene boundary timestamps from scene list."""
    boundaries = set()
    for scene in scenes:
        boundaries.add(scene.get("start", 0.0))
        boundaries.add(scene.get("end", 0.0))
    return sorted(boundaries)


def _is_near_scene_boundary(timestamp: float, boundaries: list[float], tolerance: float = 1.0) -> bool:
    """Check if a timestamp is near a scene boundary."""
    for b in boundaries:
        if abs(timestamp - b) <= tolerance:
            return True
    return False


def _merge_and_segment(
    transcript: list[dict],
    scene_boundaries: list[float],
) -> list[dict]:
    """Merge and segment transcript using rule-based approach.

    Algorithm:
        1. Start with first transcript segment as current block
        2. For each subsequent segment:
           a. If gap > threshold OR near scene boundary → finalize current block, start new
           b. If current block duration > max → finalize, start new
           c. Otherwise → merge into current block
        3. Post-process: merge blocks shorter than minimum duration
    """
    if not transcript:
        return []

    # Sort by start time
    sorted_transcript = sorted(transcript, key=lambda x: x.get("start", 0.0))

    # Phase 1: Build initial blocks
    blocks = []
    current_block = {
        "start": sorted_transcript[0].get("start", 0.0),
        "end": sorted_transcript[0].get("end", 0.0),
        "texts": [sorted_transcript[0].get("text", "")],
    }

    for seg in sorted_transcript[1:]:
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", 0.0)
        seg_text = seg.get("text", "")

        gap = seg_start - current_block["end"]
        block_duration = seg_end - current_block["start"]

        # Decide whether to split
        should_split = False

        if gap > MERGE_GAP_THRESHOLD:
            should_split = True
        elif block_duration > MAX_SEGMENT_DURATION:
            should_split = True
        elif _is_near_scene_boundary(seg_start, scene_boundaries):
            should_split = True

        if should_split:
            # Finalize current block
            blocks.append(current_block)
            current_block = {
                "start": seg_start,
                "end": seg_end,
                "texts": [seg_text],
            }
        else:
            # Merge into current block
            current_block["end"] = seg_end
            current_block["texts"].append(seg_text)

    # Don't forget the last block
    blocks.append(current_block)

    # Phase 2: Merge blocks shorter than minimum duration
    merged = []
    for block in blocks:
        duration = block["end"] - block["start"]
        if merged and duration < MIN_SEGMENT_DURATION:
            # Merge with previous block
            merged[-1]["end"] = block["end"]
            merged[-1]["texts"].extend(block["texts"])
        else:
            merged.append(block)

    # Phase 3: Build final segment list
    segments = []
    for i, block in enumerate(merged):
        segments.append({
            "start": round(block["start"], 3),
            "end": round(block["end"], 3),
            "text": " ".join(t for t in block["texts"] if t).strip(),
            "segment_index": i,
            "topic": "",  # Will be filled by LLM in future versions
        })

    return segments


def run_transcript_segmentation(ctx: PipelineContext) -> PipelineContext:
    """Pipeline step: Segment transcript into meaningful blocks.

    Saves results to both ctx.segments and the database.
    """
    if not ctx.transcript:
        logger.info("[transcript_segmentation] No transcript to segment for video %s", ctx.video_id)
        ctx.segments = []
        return ctx

    scene_boundaries = _get_scene_boundaries(ctx.scenes)

    segments = _merge_and_segment(ctx.transcript, scene_boundaries)

    ctx.segments = segments
    total_text_len = sum(len(seg.get("text", "")) for seg in segments)
    logger.info(
        "[transcript_segmentation] Created %d segments (%d chars) from %d transcript entries for video %s",
        len(segments), total_text_len, len(ctx.transcript), ctx.video_id,
    )

    # Save to DB
    try:
        from worker.pipeline.pipeline_db import save_segments
        save_segments(ctx.video_id, segments)
    except Exception as e:
        logger.warning("[transcript_segmentation] DB save failed (non-critical): %s", e)

    return ctx
