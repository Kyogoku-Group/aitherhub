#!/usr/bin/env python3
"""
Run LiveAnalysis Pipeline — Subprocess Entry Point
====================================================
Called by queue_worker.py as a subprocess to run the LiveBoost
analysis pipeline for a single job.

Usage:
    python run_live_analysis.py \
        --job-id <uuid> \
        --video-id <video_id> \
        --email <email> \
        [--total-chunks <N>] \
        [--stream-source <source>]

Exit codes:
    0 = success
    1 = failure
    2 = input validation error
"""
import argparse
import asyncio
import logging
import os
import sys

# Ensure backend/ is on sys.path so we can import app.services.*
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_live_analysis")


def parse_args():
    parser = argparse.ArgumentParser(description="Run LiveAnalysis Pipeline")
    parser.add_argument("--job-id", required=True, help="Analysis job UUID")
    parser.add_argument("--video-id", required=True, help="Video ID")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--total-chunks", type=int, default=None, help="Total chunk count")
    parser.add_argument("--stream-source", default="tiktok_live", help="Stream source type")
    return parser.parse_args()


async def main():
    args = parse_args()

    if not args.job_id or not args.video_id:
        logger.error("Missing required arguments: --job-id and --video-id")
        sys.exit(2)

    logger.info(
        f"[run_live_analysis] Starting: job={args.job_id} video={args.video_id} "
        f"chunks={args.total_chunks} source={args.stream_source}"
    )

    # Import after sys.path setup
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.live_analysis_pipeline import LiveAnalysisPipeline

    # Setup database connection
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL environment variable is required")
        sys.exit(1)

    # Convert postgres:// to postgresql+asyncpg://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url, echo=False)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            pipeline = LiveAnalysisPipeline(db)
            results = await pipeline.run(
                job_id=args.job_id,
                video_id=args.video_id,
                email=args.email,
                total_chunks=args.total_chunks,
                stream_source=args.stream_source,
            )

            sales_count = results.get("total_sales_detected", 0)
            clip_count = len(results.get("clip_candidates", []))
            logger.info(
                f"[run_live_analysis] Completed: job={args.job_id} "
                f"sales_moments={sales_count} clips={clip_count}"
            )

    except Exception as exc:
        logger.error(f"[run_live_analysis] Failed: job={args.job_id} error={exc}")
        sys.exit(1)
    finally:
        await engine.dispose()

    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
