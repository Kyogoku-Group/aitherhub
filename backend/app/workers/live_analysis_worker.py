"""
LiveBoost Analysis Worker – processes live_analysis jobs from the queue.

This worker:
  1. Dequeues messages from the Azure Storage Queue
  2. Filters for job_type == "live_analysis"
  3. Runs the LiveAnalysisPipeline for each job
  4. Updates job status in the database

Usage:
  python -m app.workers.live_analysis_worker

Environment variables:
  AZURE_STORAGE_CONNECTION_STRING – Azure Storage connection string
  AZURE_QUEUE_NAME – Queue name (default: "video-jobs")
  DATABASE_URL – PostgreSQL connection string
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

# Ensure the backend directory is in the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from azure.storage.queue import QueueClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.services.live_analysis_pipeline import LiveAnalysisPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "5"))  # seconds
VISIBILITY_TIMEOUT = int(os.getenv("WORKER_VISIBILITY_TIMEOUT", "3600"))  # 1 hour
MAX_CONCURRENT_JOBS = int(os.getenv("WORKER_MAX_CONCURRENT", "2"))


def get_queue_client() -> QueueClient:
    """Create Azure Queue client."""
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    queue_name = os.getenv("AZURE_QUEUE_NAME", "video-jobs")
    if not conn_str:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is required")
    return QueueClient.from_connection_string(conn_str, queue_name)


def get_db_session_factory():
    """Create async database session factory."""
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    # Convert postgres:// to postgresql+asyncpg://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url, echo=False)
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ──────────────────────────────────────────────
# Worker Loop
# ──────────────────────────────────────────────

async def process_message(
    message_body: dict,
    session_factory,
) -> None:
    """Process a single live_analysis job message."""
    job_id = message_body.get("job_id")
    video_id = message_body.get("video_id")
    email = message_body.get("email", "")
    total_chunks = message_body.get("total_chunks")
    stream_source = message_body.get("stream_source", "tiktok_live")

    logger.info(f"[worker] Processing job={job_id} video={video_id}")

    async with session_factory() as db:
        pipeline = LiveAnalysisPipeline(db)
        try:
            results = await pipeline.run(
                job_id=job_id,
                video_id=video_id,
                email=email,
                total_chunks=total_chunks,
                stream_source=stream_source,
            )
            logger.info(
                f"[worker] Completed job={job_id} "
                f"sales_moments={results.get('total_sales_detected', 0)}"
            )
        except Exception as exc:
            logger.error(f"[worker] Failed job={job_id}: {exc}")


async def worker_loop():
    """Main worker loop – poll queue and process messages."""
    logger.info("[worker] LiveBoost Analysis Worker starting...")

    queue_client = get_queue_client()
    session_factory = get_db_session_factory()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

    while True:
        try:
            messages = queue_client.receive_messages(
                messages_per_page=MAX_CONCURRENT_JOBS,
                visibility_timeout=VISIBILITY_TIMEOUT,
            )

            tasks = []
            for msg in messages:
                try:
                    body = json.loads(msg.content)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"[worker] Invalid message: {msg.content[:200]}")
                    queue_client.delete_message(msg)
                    continue

                # Only process live_analysis jobs
                if body.get("job_type") != "live_analysis":
                    continue

                async def process_and_delete(message, message_body):
                    async with semaphore:
                        try:
                            await process_message(message_body, session_factory)
                            queue_client.delete_message(message)
                            logger.info(f"[worker] Message deleted for job={message_body.get('job_id')}")
                        except Exception as exc:
                            logger.error(
                                f"[worker] Failed to process message: {exc}"
                            )

                tasks.append(
                    asyncio.create_task(process_and_delete(msg, body))
                )

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            else:
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as exc:
            logger.error(f"[worker] Loop error: {exc}")
            await asyncio.sleep(POLL_INTERVAL * 2)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(worker_loop())
