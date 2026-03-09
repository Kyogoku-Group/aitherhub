"""
Shared Queue Client
===================
Azure Storage Queue operations used by both API (enqueue) and Worker (dequeue).

API usage:
    from shared.queue.client import enqueue_job
    result = await enqueue_job({"job_type": "generate_clip", ...})

Worker usage:
    from shared.queue.client import get_queue_client, get_dead_letter_queue_client
    client = get_queue_client()
    messages = client.receive_messages(...)
"""
import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Dict, Optional

from azure.storage.queue import QueueClient

from shared.config import (
    AZURE_STORAGE_CONNECTION_STRING,
    AZURE_QUEUE_NAME,
    AZURE_DEAD_LETTER_QUEUE_NAME,
)

logger = logging.getLogger(__name__)


@dataclass
class EnqueueResult:
    """Result of enqueue operation with evidence for DB persistence."""
    success: bool
    message_id: Optional[str] = None
    enqueued_at: Optional[datetime] = None
    error: Optional[str] = None


def get_queue_client() -> QueueClient:
    """Get the main job queue client."""
    if not AZURE_STORAGE_CONNECTION_STRING:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is required")
    return QueueClient.from_connection_string(
        AZURE_STORAGE_CONNECTION_STRING, AZURE_QUEUE_NAME
    )


def get_dead_letter_queue_client() -> QueueClient:
    """Get or create the dead-letter queue client."""
    if not AZURE_STORAGE_CONNECTION_STRING:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is required")
    client = QueueClient.from_connection_string(
        AZURE_STORAGE_CONNECTION_STRING, AZURE_DEAD_LETTER_QUEUE_NAME
    )
    try:
        client.create_queue()
    except Exception:
        pass  # Queue already exists
    return client


async def enqueue_job(payload: Dict[str, Any]) -> EnqueueResult:
    """Push a job message to Azure Storage Queue.

    Returns EnqueueResult with message_id and enqueued_at on success,
    or error details on failure. Never raises — caller checks result.success.
    """
    try:
        client = get_queue_client()
        message = json.dumps(payload, ensure_ascii=False)
        logger.info(
            f"[queue] enqueue len={len(message)} "
            f"payload_keys={list(payload.keys())}"
        )
        resp = client.send_message(message)

        message_id = (
            resp.get("id") if isinstance(resp, dict)
            else getattr(resp, "id", None)
        )
        inserted_on = (
            resp.get("inserted_on") if isinstance(resp, dict)
            else getattr(resp, "inserted_on", None)
        )
        enqueued_at = inserted_on if inserted_on else datetime.now(timezone.utc)

        logger.info(f"[queue] enqueue OK message_id={message_id}")
        return EnqueueResult(
            success=True,
            message_id=str(message_id) if message_id else None,
            enqueued_at=enqueued_at,
        )
    except Exception as e:
        logger.error(f"[queue] enqueue FAILED: {e}")
        return EnqueueResult(success=False, error=str(e))
