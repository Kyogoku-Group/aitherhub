"""
Pipeline Runner
================
Orchestrates the video processing pipeline by executing steps in sequence.

Each step is a callable that receives a PipelineContext and returns it
(possibly modified). Steps are registered in order and executed sequentially.

If a step fails:
    - The error is recorded in context.errors
    - If the step is marked as critical, the pipeline stops
    - If non-critical, the pipeline continues with the next step

Usage:
    from worker.pipeline.pipeline_runner import PipelineRunner
    from worker.pipeline.pipeline_context import PipelineContext

    runner = PipelineRunner()
    ctx = PipelineContext(video_id="abc-123", video_path="/path/to/video.mp4")
    result = runner.run(ctx)
    print(result.summary())
"""
import sys
import time
import logging
import traceback
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from worker.pipeline.pipeline_context import PipelineContext

logger = logging.getLogger("worker.pipeline")

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(name)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@dataclass
class PipelineStep:
    """Definition of a single pipeline step."""
    name: str
    fn: Callable[[PipelineContext], PipelineContext]
    critical: bool = True
    """If True, pipeline stops on failure. If False, continues."""


class PipelineRunner:
    """Executes pipeline steps in sequence with timing and error handling."""

    def __init__(self):
        self._steps: list[PipelineStep] = []

    def add_step(
        self,
        name: str,
        fn: Callable[[PipelineContext], PipelineContext],
        critical: bool = True,
    ):
        """Register a pipeline step.

        Args:
            name: Human-readable step name (used in logs and timing).
            fn: Callable that takes PipelineContext and returns it.
            critical: If True, pipeline aborts on failure.
        """
        self._steps.append(PipelineStep(name=name, fn=fn, critical=critical))
        return self  # Allow chaining

    @property
    def step_count(self) -> int:
        return len(self._steps)

    def run(self, ctx: PipelineContext) -> PipelineContext:
        """Execute all registered steps in order.

        Returns the final PipelineContext with all results and timings.
        """
        total_start = time.time()
        total_steps = len(self._steps)

        logger.info(
            "[pipeline] Starting pipeline for video=%s (%d steps)",
            ctx.video_id, total_steps,
        )

        for i, step in enumerate(self._steps, 1):
            step_start = time.time()
            logger.info(
                "[pipeline] [%d/%d] %s — starting",
                i, total_steps, step.name,
            )

            try:
                ctx = step.fn(ctx)
                elapsed = time.time() - step_start
                ctx.step_timings[step.name] = round(elapsed, 2)

                logger.info(
                    "[pipeline] [%d/%d] %s — completed (%.2fs)",
                    i, total_steps, step.name, elapsed,
                )

            except Exception as e:
                elapsed = time.time() - step_start
                ctx.step_timings[step.name] = round(elapsed, 2)
                error_msg = f"{type(e).__name__}: {e}"
                ctx.errors[step.name] = error_msg

                logger.error(
                    "[pipeline] [%d/%d] %s — FAILED (%.2fs): %s",
                    i, total_steps, step.name, elapsed, error_msg,
                )
                logger.debug(traceback.format_exc())

                if step.critical:
                    logger.error(
                        "[pipeline] Pipeline aborted at step '%s' (critical=True)",
                        step.name,
                    )
                    break
                else:
                    logger.warning(
                        "[pipeline] Continuing despite failure in '%s' (critical=False)",
                        step.name,
                    )

        total_elapsed = time.time() - total_start
        ctx.step_timings["_total"] = round(total_elapsed, 2)

        summary = ctx.summary()
        logger.info(
            "[pipeline] Pipeline finished for video=%s — "
            "scenes=%d, transcript=%d, segments=%d, events=%d, "
            "sales_moments=%d, clips=%d, errors=%d, total_time=%.2fs",
            ctx.video_id,
            summary["scenes_count"],
            summary["transcript_segments"],
            summary["segments_count"],
            summary["events_count"],
            summary["sales_moments_count"],
            summary["clips_count"],
            len(summary["errors"]),
            total_elapsed,
        )

        return ctx


def build_default_pipeline() -> PipelineRunner:
    """Build the default AitherHub video processing pipeline.

    Pipeline steps:
        1. scene_detection      — Detect scene boundaries
        2. speech_extraction    — Extract audio from video
        3. speech_to_text       — Transcribe audio to text
        4. transcript_segmentation — Segment transcript into meaning units
        5. event_detection      — Detect events (product_show, CTA, etc.)
        6. sales_moment_detection — Detect high-conversion moments
        7. clip_generation      — Generate clips from sales moments
    """
    from worker.pipeline.pipeline_steps.scene_detection import run_scene_detection
    from worker.pipeline.pipeline_steps.speech_extraction import run_speech_extraction
    from worker.pipeline.pipeline_steps.speech_to_text import run_speech_to_text
    from worker.pipeline.pipeline_steps.transcript_segmentation import run_transcript_segmentation
    from worker.pipeline.pipeline_steps.event_detection import run_event_detection
    from worker.pipeline.pipeline_steps.sales_moment_detection import run_sales_moment_detection
    from worker.pipeline.pipeline_steps.clip_generator import run_clip_generation

    runner = PipelineRunner()
    runner.add_step("scene_detection", run_scene_detection, critical=False)
    runner.add_step("speech_extraction", run_speech_extraction, critical=True)
    runner.add_step("speech_to_text", run_speech_to_text, critical=True)
    runner.add_step("transcript_segmentation", run_transcript_segmentation, critical=False)
    runner.add_step("event_detection", run_event_detection, critical=False)
    runner.add_step("sales_moment_detection", run_sales_moment_detection, critical=False)
    runner.add_step("clip_generation", run_clip_generation, critical=False)

    return runner


def run_pipeline(
    video_id: str,
    video_path: str,
    blob_url: str = "",
    user_id: str = "",
) -> PipelineContext:
    """Convenience function to run the full default pipeline.

    Args:
        video_id: Unique video identifier.
        video_path: Local path to the video file.
        blob_url: Original blob URL (for reference).
        user_id: Owner user ID.

    Returns:
        PipelineContext with all results populated.
    """
    ctx = PipelineContext(
        video_id=video_id,
        video_path=video_path,
        blob_url=blob_url,
        user_id=user_id,
    )

    runner = build_default_pipeline()
    return runner.run(ctx)
