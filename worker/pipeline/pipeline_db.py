"""
Pipeline DB Operations
=======================
Saves pipeline step results to the database.
Uses shared.db.session for database access.

All functions are synchronous wrappers around async DB operations,
designed to be called from pipeline steps.
"""
import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("worker.pipeline.db")


def save_scenes(video_id: str, scenes: list[dict]):
    """Save scene detection results to video_scenes table."""
    if not scenes:
        return
    try:
        from shared.db.session import get_session, run_sync
        from sqlalchemy import text

        async def _save():
            async with get_session() as session:
                # Delete existing scenes for this video (idempotent)
                await session.execute(
                    text("DELETE FROM video_scenes WHERE video_id = :vid"),
                    {"vid": video_id},
                )
                for scene in scenes:
                    await session.execute(
                        text("""
                            INSERT INTO video_scenes
                                (video_id, scene_index, start_time, end_time, metadata)
                            VALUES (:vid, :idx, :start, :end, :meta)
                        """),
                        {
                            "vid": video_id,
                            "idx": scene.get("scene_index", 0),
                            "start": scene["start"],
                            "end": scene["end"],
                            "meta": "{}",
                        },
                    )

        run_sync(_save())
        logger.info("[pipeline.db] Saved %d scenes for video %s", len(scenes), video_id)
    except Exception as e:
        logger.error("[pipeline.db] Failed to save scenes: %s", e)
        raise


def save_transcripts(video_id: str, transcript: list[dict]):
    """Save speech-to-text results to video_transcripts table."""
    if not transcript:
        return
    try:
        from shared.db.session import get_session, run_sync
        from sqlalchemy import text

        async def _save():
            async with get_session() as session:
                await session.execute(
                    text("DELETE FROM video_transcripts WHERE video_id = :vid"),
                    {"vid": video_id},
                )
                for i, seg in enumerate(transcript):
                    await session.execute(
                        text("""
                            INSERT INTO video_transcripts
                                (video_id, segment_index, start_time, end_time,
                                 text, confidence, language)
                            VALUES (:vid, :idx, :start, :end, :text, :conf, :lang)
                        """),
                        {
                            "vid": video_id,
                            "idx": i,
                            "start": seg.get("start", 0.0),
                            "end": seg.get("end", 0.0),
                            "text": seg.get("text", ""),
                            "conf": seg.get("confidence", 0.0),
                            "lang": seg.get("language", "ja"),
                        },
                    )

        run_sync(_save())
        logger.info("[pipeline.db] Saved %d transcript segments for video %s",
                     len(transcript), video_id)
    except Exception as e:
        logger.error("[pipeline.db] Failed to save transcripts: %s", e)
        raise


def save_segments(video_id: str, segments: list[dict]):
    """Save transcript segmentation results to video_segments table."""
    if not segments:
        return
    try:
        from shared.db.session import get_session, run_sync
        from sqlalchemy import text

        async def _save():
            async with get_session() as session:
                await session.execute(
                    text("DELETE FROM video_segments WHERE video_id = :vid"),
                    {"vid": video_id},
                )
                for seg in segments:
                    await session.execute(
                        text("""
                            INSERT INTO video_segments
                                (video_id, segment_index, start_time, end_time, text, topic)
                            VALUES (:vid, :idx, :start, :end, :text, :topic)
                        """),
                        {
                            "vid": video_id,
                            "idx": seg.get("segment_index", 0),
                            "start": seg["start"],
                            "end": seg["end"],
                            "text": seg.get("text", ""),
                            "topic": seg.get("topic", ""),
                        },
                    )

        run_sync(_save())
        logger.info("[pipeline.db] Saved %d segments for video %s",
                     len(segments), video_id)
    except Exception as e:
        logger.error("[pipeline.db] Failed to save segments: %s", e)
        raise


def save_events(video_id: str, events: list[dict]):
    """Save event detection results to video_events table."""
    if not events:
        return
    try:
        from shared.db.session import get_session, run_sync
        from sqlalchemy import text

        async def _save():
            async with get_session() as session:
                await session.execute(
                    text("DELETE FROM video_events WHERE video_id = :vid"),
                    {"vid": video_id},
                )
                for evt in events:
                    await session.execute(
                        text("""
                            INSERT INTO video_events
                                (video_id, event_type, start_time, end_time,
                                 confidence, description)
                            VALUES (:vid, :type, :start, :end, :conf, :desc)
                        """),
                        {
                            "vid": video_id,
                            "type": evt.get("event_type", "unknown"),
                            "start": evt["start"],
                            "end": evt["end"],
                            "conf": evt.get("confidence", 0.0),
                            "desc": evt.get("description", ""),
                        },
                    )

        run_sync(_save())
        logger.info("[pipeline.db] Saved %d events for video %s",
                     len(events), video_id)
    except Exception as e:
        logger.error("[pipeline.db] Failed to save events: %s", e)
        raise


def save_sales_moments(video_id: str, sales_moments: list[dict]):
    """Save sales moment detection results to video_sales_moments table."""
    if not sales_moments:
        return
    try:
        from shared.db.session import get_session, run_sync
        from sqlalchemy import text
        import json

        async def _save():
            async with get_session() as session:
                await session.execute(
                    text("DELETE FROM video_sales_moments WHERE video_id = :vid AND source = 'pipeline'"),
                    {"vid": video_id},
                )
                for sm in sales_moments:
                    await session.execute(
                        text("""
                            INSERT INTO video_sales_moments
                                (video_id, start_time, end_time, score, reason,
                                 source, events)
                            VALUES (:vid, :start, :end, :score, :reason,
                                    'pipeline', :events)
                        """),
                        {
                            "vid": video_id,
                            "start": sm["start"],
                            "end": sm["end"],
                            "score": sm.get("score", 0.0),
                            "reason": sm.get("reason", ""),
                            "events": json.dumps(sm.get("events", []),
                                                  ensure_ascii=False),
                        },
                    )

        run_sync(_save())
        logger.info("[pipeline.db] Saved %d sales moments for video %s",
                     len(sales_moments), video_id)
    except Exception as e:
        logger.error("[pipeline.db] Failed to save sales moments: %s", e)
        raise


def save_pipeline_run(video_id: str, ctx_summary: dict, worker_id: str = ""):
    """Save pipeline run metadata to video_pipeline_runs table."""
    try:
        from shared.db.session import get_session, run_sync
        from sqlalchemy import text
        import json

        status = "completed" if not ctx_summary.get("errors") else "failed"

        async def _save():
            async with get_session() as session:
                await session.execute(
                    text("""
                        INSERT INTO video_pipeline_runs
                            (video_id, worker_id, status, step_timings, errors,
                             summary, finished_at)
                        VALUES (:vid, :wid, :status, :timings, :errors,
                                :summary, NOW())
                    """),
                    {
                        "vid": video_id,
                        "wid": worker_id,
                        "status": status,
                        "timings": json.dumps(ctx_summary.get("step_timings", {})),
                        "errors": json.dumps(ctx_summary.get("errors", {})),
                        "summary": json.dumps(ctx_summary, ensure_ascii=False),
                    },
                )

        run_sync(_save())
        logger.info("[pipeline.db] Saved pipeline run for video %s (status=%s)",
                     video_id, status)
    except Exception as e:
        logger.error("[pipeline.db] Failed to save pipeline run: %s", e)


def save_pipeline_results(ctx, worker_id: str = ""):
    """Save all pipeline results to the database.

    This is the main entry point called by queue_worker after pipeline
    execution completes. It saves each step's output to its respective
    table, then records the pipeline run metadata.

    Args:
        ctx: PipelineContext with populated step outputs.
        worker_id: Identifier of the worker that ran the pipeline.
    """
    video_id = ctx.video_id

    logger.info("[pipeline.db] Saving all results for video %s", video_id)

    # Save each step's output (order doesn't matter, each is independent)
    try:
        save_scenes(video_id, ctx.scenes)
    except Exception as e:
        logger.warning("[pipeline.db] save_scenes failed: %s", e)

    try:
        save_transcripts(video_id, ctx.transcript)
    except Exception as e:
        logger.warning("[pipeline.db] save_transcripts failed: %s", e)

    try:
        save_segments(video_id, ctx.segments)
    except Exception as e:
        logger.warning("[pipeline.db] save_segments failed: %s", e)

    try:
        save_events(video_id, ctx.events)
    except Exception as e:
        logger.warning("[pipeline.db] save_events failed: %s", e)

    try:
        save_sales_moments(video_id, ctx.sales_moments)
    except Exception as e:
        logger.warning("[pipeline.db] save_sales_moments failed: %s", e)

    # Save pipeline run metadata
    try:
        save_pipeline_run(video_id, ctx.summary(), worker_id=worker_id)
    except Exception as e:
        logger.warning("[pipeline.db] save_pipeline_run failed: %s", e)

    logger.info("[pipeline.db] All results saved for video %s", video_id)
