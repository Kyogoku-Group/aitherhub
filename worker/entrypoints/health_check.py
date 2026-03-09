#!/usr/bin/env python3
"""
Worker Health Check Server
===========================
Lightweight HTTP server for worker health monitoring.
Runs alongside the queue worker on a separate port.

Checks:
    1. Worker process is alive
    2. Queue is reachable
    3. Database is reachable
    4. ffmpeg is available
    5. Temp directory is writable
    6. Disk space is sufficient

Start:
    python -m worker.entrypoints.health_check

Endpoints:
    GET /health         → Full health check
    GET /health/live    → Liveness probe (is process running?)
    GET /health/ready   → Readiness probe (can process jobs?)
"""
import os
import sys
import json
import time
import shutil
import subprocess
import tempfile
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shared.config import (
    AZURE_STORAGE_CONNECTION_STRING,
    AZURE_QUEUE_NAME,
    ENVIRONMENT,
    DATABASE_URL,
)

HEALTH_PORT = int(os.getenv("WORKER_HEALTH_PORT", "8081"))
BATCH_DIR = str(PROJECT_ROOT / "worker" / "batch")

_start_time = time.time()


def check_ffmpeg() -> dict:
    """Check if ffmpeg is available and working."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
            return {"status": "ok", "version": version_line}
        return {"status": "error", "detail": f"exit_code={result.returncode}"}
    except FileNotFoundError:
        return {"status": "error", "detail": "ffmpeg not found in PATH"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "detail": "ffmpeg version check timed out"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_temp_dir() -> dict:
    """Check if temp directory is writable."""
    try:
        with tempfile.NamedTemporaryFile(dir=BATCH_DIR, suffix=".healthcheck", delete=True) as f:
            f.write(b"health_check")
            f.flush()
        return {"status": "ok", "path": BATCH_DIR}
    except Exception as e:
        return {"status": "error", "detail": str(e), "path": BATCH_DIR}


def check_disk_space() -> dict:
    """Check available disk space."""
    try:
        usage = shutil.disk_usage(BATCH_DIR)
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_pct = (usage.used / usage.total) * 100
        status = "ok" if free_gb > 5.0 else ("warning" if free_gb > 2.0 else "error")
        return {
            "status": status,
            "free_gb": round(free_gb, 2),
            "total_gb": round(total_gb, 2),
            "used_pct": round(used_pct, 1),
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_queue() -> dict:
    """Check if Azure Storage Queue is reachable."""
    try:
        from shared.queue.client import get_queue_client
        client = get_queue_client()
        props = client.get_queue_properties()
        count = props.approximate_message_count
        return {"status": "ok", "queue": AZURE_QUEUE_NAME, "approximate_count": count}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_database() -> dict:
    """Check if database is reachable."""
    try:
        from shared.db.session import check_connection, run_sync
        run_sync(check_connection())
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_storage() -> dict:
    """Check if Azure Blob Storage is accessible."""
    try:
        from shared.storage.blob import get_blob_service_client
        client = get_blob_service_client()
        # List containers (lightweight operation to verify connectivity)
        containers = list(client.list_containers(results_per_page=1))
        return {"status": "ok", "detail": "Blob storage reachable"}
    except ImportError:
        # Fallback: try direct connection test
        try:
            from azure.storage.blob import BlobServiceClient
            conn_str = AZURE_STORAGE_CONNECTION_STRING
            if not conn_str:
                return {"status": "error", "detail": "No connection string"}
            client = BlobServiceClient.from_connection_string(conn_str)
            props = client.get_account_information()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_worker_process() -> dict:
    """Check if the main worker process is running."""
    lock_file = Path("/tmp/simple_worker.lock")
    if lock_file.exists():
        try:
            pid = int(lock_file.read_text().strip())
            # Check if process is alive
            os.kill(pid, 0)
            return {"status": "ok", "pid": pid}
        except (ValueError, ProcessLookupError):
            return {"status": "error", "detail": "Worker process not running (stale lock)"}
        except PermissionError:
            return {"status": "ok", "detail": "Process exists (permission denied for signal)"}
    return {"status": "error", "detail": "No lock file found"}


def full_health_check() -> dict:
    """Run all health checks."""
    checks = {
        "worker_process": check_worker_process(),
        "ffmpeg": check_ffmpeg(),
        "temp_dir": check_temp_dir(),
        "disk_space": check_disk_space(),
        "queue": check_queue(),
        "database": check_database(),
        "storage": check_storage(),
    }

    all_ok = all(c["status"] == "ok" for c in checks.values())
    has_error = any(c["status"] == "error" for c in checks.values())

    if all_ok:
        overall = "healthy"
    elif has_error:
        overall = "unhealthy"
    else:
        overall = "degraded"

    return {
        "status": overall,
        "environment": ENVIRONMENT,
        "uptime_seconds": round(time.time() - _start_time, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health check endpoints."""

    def do_GET(self):
        if self.path == "/health" or self.path == "/health/":
            result = full_health_check()
            status_code = 200 if result["status"] != "unhealthy" else 503
        elif self.path == "/health/live":
            result = {"status": "ok", "uptime_seconds": round(time.time() - _start_time, 1)}
            status_code = 200
        elif self.path == "/health/ready":
            checks = {
                "worker_process": check_worker_process(),
                "queue": check_queue(),
                "database": check_database(),
            }
            has_error = any(c["status"] == "error" for c in checks.values())
            result = {
                "status": "ready" if not has_error else "not_ready",
                "checks": checks,
            }
            status_code = 200 if not has_error else 503
        else:
            result = {"error": "not found"}
            status_code = 404

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result, indent=2).encode())

    def log_message(self, format, *args):
        """Suppress default access logs to reduce noise."""
        pass


def main():
    print(f"[worker-health] Starting health check server on port {HEALTH_PORT}")
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[worker-health] Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
