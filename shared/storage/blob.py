"""
Shared Blob Storage Utilities
==============================
Azure Blob Storage operations used by both API and Worker.

Provides:
    - parse_blob_url: Extract account/container/blob from URL
    - upload_to_blob: Upload local file to Azure Blob
    - generate_sas_url: Generate SAS URL for blob access
    - get_blob_service_client: Get BlobServiceClient instance
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, unquote
from typing import Optional

from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    generate_blob_sas,
)

from shared.config import (
    AZURE_STORAGE_CONNECTION_STRING,
    AZURE_BLOB_CONTAINER,
    AZURE_BLOB_SAS_EXP_MINUTES,
)

logger = logging.getLogger(__name__)


def _parse_account_from_conn_str(conn_str: str) -> dict:
    """Extract AccountName and AccountKey from connection string."""
    parts = conn_str.split(";")
    out = {"AccountName": None, "AccountKey": None}
    for p in parts:
        if p.startswith("AccountName="):
            out["AccountName"] = p.split("=", 1)[1]
        if p.startswith("AccountKey="):
            out["AccountKey"] = p.split("=", 1)[1]
    return out


def parse_blob_url(blob_url: str) -> dict:
    """Parse an Azure Blob URL into components.

    Returns:
        dict with keys: account_name, container_name, blob_name
    """
    parsed = urlparse(blob_url)
    # e.g. https://account.blob.core.windows.net/container/path/to/blob
    host_parts = parsed.hostname.split(".") if parsed.hostname else []
    account_name = host_parts[0] if host_parts else ""

    path_parts = parsed.path.lstrip("/").split("/", 1)
    container_name = path_parts[0] if len(path_parts) > 0 else ""
    blob_name = unquote(path_parts[1]) if len(path_parts) > 1 else ""

    return {
        "account_name": account_name,
        "container_name": container_name,
        "blob_name": blob_name,
    }


def get_blob_service_client() -> BlobServiceClient:
    """Get BlobServiceClient from connection string."""
    if not AZURE_STORAGE_CONNECTION_STRING:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING is required")
    return BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)


def upload_to_blob(
    local_path: str,
    blob_name: str,
    container: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Optional[str]:
    """Upload a local file to Azure Blob Storage.

    Returns:
        SAS URL of the uploaded blob, or None on failure.
    """
    container = container or AZURE_BLOB_CONTAINER
    try:
        service_client = get_blob_service_client()
        blob_client = service_client.get_blob_client(container, blob_name)

        kwargs = {"overwrite": True}
        if content_type:
            from azure.storage.blob import ContentSettings
            kwargs["content_settings"] = ContentSettings(content_type=content_type)

        with open(local_path, "rb") as f:
            blob_client.upload_blob(f, **kwargs)

        # Generate SAS URL
        sas_url = generate_sas_url(blob_name, container=container)
        logger.info(f"[blob] Uploaded {blob_name} ({os.path.getsize(local_path)} bytes)")
        return sas_url
    except Exception as e:
        logger.error(f"[blob] Upload failed for {blob_name}: {e}")
        return None


def generate_sas_url(
    blob_name: str,
    container: Optional[str] = None,
    expiry_minutes: Optional[int] = None,
    permissions: str = "r",
) -> str:
    """Generate a SAS URL for a blob.

    Args:
        blob_name: Name of the blob
        container: Container name (defaults to AZURE_BLOB_CONTAINER)
        expiry_minutes: SAS expiry in minutes (defaults to config)
        permissions: SAS permissions string (default: read-only)
    """
    container = container or AZURE_BLOB_CONTAINER
    expiry_minutes = expiry_minutes or AZURE_BLOB_SAS_EXP_MINUTES

    account_info = _parse_account_from_conn_str(AZURE_STORAGE_CONNECTION_STRING)
    account_name = account_info["AccountName"]
    account_key = account_info["AccountKey"]

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read="r" in permissions),
        expiry=datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes),
    )

    return f"https://{account_name}.blob.core.windows.net/{container}/{blob_name}?{sas_token}"
