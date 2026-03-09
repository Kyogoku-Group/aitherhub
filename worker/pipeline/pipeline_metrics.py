"""
Pipeline Metrics
=================
Logs performance metrics for each pipeline step.

Integrates with the existing worker.recovery.metrics_logger
and adds pipeline-specific structured logging.

Usage:
    from worker.pipeline.pipeline_metrics import log_pipeline_metrics
    log_pipeline_metrics(ctx)
"""
import sys
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from worker.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("worker.pipeline.metrics")

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(name)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def log_pipeline_metrics(ctx: PipelineContext):
    """Log structured metrics for the completed pipeline run.

    Outputs one log line per step, plus a summary line.
    Format is designed for easy parsing by log aggregation tools.
    """
    video_id = ctx.video_id
    timings = ctx.step_timings

    # Log each step's timing
    for step_name, duration in timings.items():
        if step_name.startswith("_"):
            continue  # Skip internal keys like _total
        logger.info(
            "pipeline.%s_time video_id=%s duration=%.2fs",
            step_name, video_id, duration,
        )

    # Log summary
    summary = {
        "video_id": video_id,
        "total_time_s": timings.get("_total", 0.0),
        "scene_detection_time_s": timings.get("scene_detection", 0.0),
        "speech_extraction_time_s": timings.get("speech_extraction", 0.0),
        "speech_to_text_time_s": timings.get("speech_to_text", 0.0),
        "transcript_segmentation_time_s": timings.get("transcript_segmentation", 0.0),
        "event_detection_time_s": timings.get("event_detection", 0.0),
        "sales_moment_detection_time_s": timings.get("sales_moment_detection", 0.0),
        "clip_generation_time_s": timings.get("clip_generation", 0.0),
        "scenes_count": len(ctx.scenes),
        "transcript_count": len(ctx.transcript),
        "segments_count": len(ctx.segments),
        "events_count": len(ctx.events),
        "sales_moments_count": len(ctx.sales_moments),
        "clips_count": len(ctx.clips),
        "errors_count": len(ctx.errors),
        "video_duration_s": ctx.video_duration,
    }

    logger.info(
        "pipeline.summary %s",
        json.dumps(summary, ensure_ascii=False),
    )

    # Log errors if any
    if ctx.errors:
        for step_name, error_msg in ctx.errors.items():
            logger.error(
                "pipeline.error video_id=%s step=%s error=%s",
                video_id, step_name, error_msg,
            )

    return summary


def log_step_result(step_name: str, ctx: PipelineContext, **extra):
    """Log the result of a single pipeline step with extra metadata.

    Can be called from within a step for more granular logging.
    """
    data = {
        "video_id": ctx.video_id,
        "step": step_name,
        "duration_s": ctx.step_timings.get(step_name, 0.0),
        **extra,
    }
    logger.info(
        "pipeline.step_result %s",
        json.dumps(data, ensure_ascii=False),
    )
