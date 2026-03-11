import json
import os
import logging
from datetime import datetime, timezone
from typing import Any, Dict
from dataclasses import dataclass

from azure.storage.queue import QueueClient

logger = logging.getLogger(__name__)
if not logger.handlers:
    # Fallback basic config so logs appear in stdout if app didn't configure logging
    logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)


@dataclass
class EnqueueResult:
    """Result of enqueue operation with evidence for DB persistence."""
    success: bool
    message_id: str | None = None
    enqueued_at: datetime | None = None
    error: str | None = None


def _get_queue_client() -> QueueClient:
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    queue_name = os.getenv("AZURE_QUEUE_NAME", "video-jobs")
    if not conn_str:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is required for queue messaging")

    # Light logging without leaking full secret
    account_name = None
    for part in conn_str.split(";"):
        if part.startswith("AccountName="):
            account_name = part.split("=", 1)[1]
            break
    logger.info(f"[queue] connect account={account_name} queue={queue_name}")

    client = QueueClient.from_connection_string(conn_str, queue_name)
    try:
        client.create_queue()
    except Exception as _e:
        logger.debug(f"Non-critical error suppressed: {_e}")
    return client


async def enqueue_job(payload: Dict[str, Any]) -> EnqueueResult:
    """Push a job message to Azure Storage Queue.

    Returns EnqueueResult with message_id and enqueued_at on success,
    or error details on failure. Never raises — caller checks result.success.
    """
    try:
        client = _get_queue_client()
        message = json.dumps(payload, ensure_ascii=False)
        logger.info(f"[queue] enqueue len={len(message)} payload_keys={list(payload.keys())}")
        resp = client.send_message(message)

        # Extract evidence from Azure response
        message_id = resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)
        inserted_on = resp.get("inserted_on") if isinstance(resp, dict) else getattr(resp, "inserted_on", None)
        enqueued_at = inserted_on if inserted_on else datetime.now(timezone.utc)

        logger.info(f"[queue] enqueue OK message_id={message_id} enqueued_at={enqueued_at}")
        return EnqueueResult(
            success=True,
            message_id=str(message_id) if message_id else None,
            enqueued_at=enqueued_at,
        )
    except Exception as e:
        logger.error(f"[queue] enqueue FAILED: {e}")
        return EnqueueResult(
            success=False,
            error=str(e),
        )
