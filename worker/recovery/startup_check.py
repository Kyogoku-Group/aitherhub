"""
Worker Startup Self Check
==========================
Verifies all dependencies before the worker starts processing jobs.

Checks:
    1. FFmpeg version and availability
    2. Temp directory write permission
    3. Queue connection (Azure Storage Queue)
    4. Database connection (PostgreSQL)

If any check fails, the worker exits immediately with a non-zero code.
This prevents a broken worker from sitting idle and consuming resources.

Usage:
    from worker.recovery.startup_check import run_startup_checks
    run_startup_checks()  # Exits if any check fails
"""
import os
import sys
import subprocess
import tempfile
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("worker.startup")

# Configure logging if not already configured
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(name)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class StartupCheckError(Exception):
    """Raised when a startup check fails."""
    pass


def check_ffmpeg() -> dict:
    """Check FFmpeg is installed and accessible."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise StartupCheckError(
                f"ffmpeg returned exit code {result.returncode}"
            )
        version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
        return {"status": "ok", "version": version_line}
    except FileNotFoundError:
        raise StartupCheckError(
            "ffmpeg not found in PATH. Install with: apt install ffmpeg"
        )
    except subprocess.TimeoutExpired:
        raise StartupCheckError("ffmpeg version check timed out (>10s)")


def check_temp_dir() -> dict:
    """Check temp directory is writable."""
    from worker.recovery.temp_manager import TEMP_BASE

    try:
        TEMP_BASE.mkdir(parents=True, exist_ok=True)
        test_file = TEMP_BASE / ".startup_check"
        test_file.write_text("startup_check")
        test_file.unlink()
        return {"status": "ok", "path": str(TEMP_BASE)}
    except PermissionError:
        raise StartupCheckError(
            f"Cannot write to temp directory: {TEMP_BASE}. "
            f"Check permissions."
        )
    except Exception as e:
        raise StartupCheckError(
            f"Temp directory check failed: {e}"
        )


def check_queue_connection() -> dict:
    """Check Azure Storage Queue is reachable."""
    try:
        from shared.queue.client import get_queue_client
        from shared.config import AZURE_QUEUE_NAME

        client = get_queue_client()
        props = client.get_queue_properties()
        count = props.approximate_message_count
        return {
            "status": "ok",
            "queue": AZURE_QUEUE_NAME,
            "approximate_count": count,
        }
    except ImportError as e:
        raise StartupCheckError(
            f"Missing dependency for queue connection: {e}"
        )
    except Exception as e:
        raise StartupCheckError(
            f"Queue connection failed: {e}"
        )


def check_database_connection() -> dict:
    """Check PostgreSQL database is reachable."""
    try:
        from shared.db.session import get_session, run_sync
        from sqlalchemy import text

        async def _check():
            async with get_session() as session:
                result = await session.execute(text("SELECT 1"))
                return result.scalar()

        val = run_sync(_check())
        if val != 1:
            raise StartupCheckError(
                f"Database returned unexpected value: {val}"
            )
        return {"status": "ok"}
    except StartupCheckError:
        raise
    except ImportError as e:
        raise StartupCheckError(
            f"Missing dependency for database connection: {e}"
        )
    except Exception as e:
        raise StartupCheckError(
            f"Database connection failed: {e}"
        )


def run_startup_checks():
    """Run all startup checks. Exits with code 1 if any check fails.

    Returns a dict of all check results on success.
    """
    checks = [
        ("ffmpeg", check_ffmpeg),
        ("temp_dir", check_temp_dir),
        ("queue", check_queue_connection),
        ("database", check_database_connection),
    ]

    results = {}
    all_passed = True

    logger.info("[startup] Running self-check...")
    logger.info("[startup] ================================")

    for name, check_fn in checks:
        try:
            result = check_fn()
            results[name] = result
            detail = ""
            if "version" in result:
                detail = f" ({result['version']})"
            elif "queue" in result:
                detail = f" (queue={result['queue']}, msgs={result.get('approximate_count', '?')})"
            elif "path" in result:
                detail = f" (path={result['path']})"
            logger.info("[startup]   %s: OK%s", name.upper(), detail)
        except StartupCheckError as e:
            results[name] = {"status": "error", "detail": str(e)}
            logger.error("[startup]   %s: FAILED — %s", name.upper(), e)
            all_passed = False

    logger.info("[startup] ================================")

    if not all_passed:
        logger.error(
            "[startup] FATAL: One or more startup checks failed. "
            "Worker cannot start. Exiting."
        )
        sys.exit(1)

    logger.info("[startup] All checks passed. Worker is ready to start.")
    return results
