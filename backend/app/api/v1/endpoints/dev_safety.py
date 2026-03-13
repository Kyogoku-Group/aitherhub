"""
Dev Safety API — Layer 2 of the 4-Layer Defense System.

Provides file-level locking to prevent concurrent edits by multiple
Manus sessions (or any automated agent). Locks are stored in-memory
with auto-expiry so a crashed session never blocks the next one.

Endpoints:
  POST   /admin/dev-safety/lock      — Acquire locks on files
  POST   /admin/dev-safety/unlock    — Release locks
  POST   /admin/dev-safety/clear     — Force-clear all locks (session start)
  GET    /admin/dev-safety/status    — Show current lock state

Design decisions:
  - In-memory dict (not DB) — locks are ephemeral and must not survive
    a deploy. A fresh deploy = fresh locks = clean slate.
  - Auto-expiry (default 2 hours) — if a session crashes, locks expire.
  - Admin-key protected — same X-Admin-Key as other admin endpoints.
  - Overhead: < 1ms per call (dict lookup).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from loguru import logger
import os

router = APIRouter(prefix="/admin/dev-safety", tags=["Dev Safety"])

# ── In-memory lock store ────────────────────────────────────────
# Key: file path (relative to repo root, e.g. "backend/app/main.py")
# Value: {"session": str, "locked_at": datetime, "expires_at": datetime}
_file_locks: Dict[str, dict] = {}

DEFAULT_LOCK_DURATION_MINUTES = 120  # 2 hours


# ── Auth helper ─────────────────────────────────────────────────
def _check_admin(key: Optional[str]):
    expected = os.getenv("ADMIN_API_KEY", "aither:hub")
    if key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Request / Response schemas ──────────────────────────────────
class LockRequest(BaseModel):
    session_id: str  # e.g. "manus-session-20260313-abc"
    files: List[str]  # relative paths to lock
    duration_minutes: int = DEFAULT_LOCK_DURATION_MINUTES


class UnlockRequest(BaseModel):
    session_id: str
    files: List[str]


class LockResult(BaseModel):
    acquired: List[str]
    denied: List[dict]  # [{"file": str, "held_by": str, "expires_at": str}]


# ── Helpers ─────────────────────────────────────────────────────
def _now():
    return datetime.now(timezone.utc)


def _purge_expired():
    """Remove expired locks."""
    expired = [f for f, info in _file_locks.items() if info["expires_at"] < _now()]
    for f in expired:
        del _file_locks[f]
    if expired:
        logger.info(f"[dev-safety] Purged {len(expired)} expired locks")


# ── Endpoints ───────────────────────────────────────────────────

@router.post("/lock", response_model=LockResult)
async def acquire_locks(
    req: LockRequest,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """
    Acquire file locks for a session.

    If any file is already locked by a DIFFERENT session (and not expired),
    the lock is denied for that file. Files already locked by the SAME
    session are silently re-acquired (idempotent).
    """
    _check_admin(x_admin_key)
    _purge_expired()

    acquired = []
    denied = []
    expires_at = _now() + timedelta(minutes=req.duration_minutes)

    for filepath in req.files:
        existing = _file_locks.get(filepath)
        if existing and existing["session"] != req.session_id:
            # Locked by another session
            denied.append({
                "file": filepath,
                "held_by": existing["session"],
                "expires_at": existing["expires_at"].isoformat(),
            })
        else:
            # Free or same session — acquire/renew
            _file_locks[filepath] = {
                "session": req.session_id,
                "locked_at": _now(),
                "expires_at": expires_at,
            }
            acquired.append(filepath)

    if denied:
        logger.warning(
            f"[dev-safety] Session {req.session_id} denied locks: "
            f"{[d['file'] for d in denied]}"
        )
    if acquired:
        logger.info(
            f"[dev-safety] Session {req.session_id} acquired locks: {acquired}"
        )

    return LockResult(acquired=acquired, denied=denied)


@router.post("/unlock")
async def release_locks(
    req: UnlockRequest,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """Release file locks held by a session."""
    _check_admin(x_admin_key)

    released = []
    skipped = []
    for filepath in req.files:
        existing = _file_locks.get(filepath)
        if existing and existing["session"] == req.session_id:
            del _file_locks[filepath]
            released.append(filepath)
        else:
            skipped.append(filepath)

    logger.info(f"[dev-safety] Session {req.session_id} released: {released}")
    return {"released": released, "skipped": skipped}


@router.post("/clear")
async def clear_all_locks(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """
    Force-clear ALL locks. Used at session start to ensure a clean slate.
    This is safe because only one Manus session should be active at a time.
    """
    _check_admin(x_admin_key)
    count = len(_file_locks)
    _file_locks.clear()
    logger.info(f"[dev-safety] Cleared all {count} locks")
    return {"cleared": count, "message": "All file locks cleared"}


@router.get("/status")
async def lock_status(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """Show current lock state (for debugging)."""
    _check_admin(x_admin_key)
    _purge_expired()

    locks = []
    for filepath, info in _file_locks.items():
        locks.append({
            "file": filepath,
            "session": info["session"],
            "locked_at": info["locked_at"].isoformat(),
            "expires_at": info["expires_at"].isoformat(),
            "remaining_minutes": max(
                0,
                int((info["expires_at"] - _now()).total_seconds() / 60)
            ),
        })

    return {
        "total_locks": len(locks),
        "locks": locks,
    }
