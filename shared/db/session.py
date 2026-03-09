"""
Shared Database Session
=======================
Single source of truth for database connections.
Used by both API service and Worker service.

Usage (async — API):
    from shared.db.session import get_async_session
    async for session in get_async_session():
        result = await session.execute(text("SELECT 1"))

Usage (sync wrapper — Worker):
    from shared.db.session import run_sync
    def my_sync_function():
        run_sync(my_async_db_operation())
"""
import asyncio
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from shared.config import DATABASE_URL, prepare_database_url


# Lazy initialization — engine is created on first use.
# This allows importing this module even when DATABASE_URL is not yet set.
_engine = None
_session_factory = None


def _get_engine():
    """Get or create the async engine (lazy init)."""
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. Cannot create database engine."
            )
        cleaned_url, connect_args = prepare_database_url(DATABASE_URL)
        _engine = create_async_engine(
            cleaned_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=300,
            echo=False,
            connect_args=connect_args,
        )
    return _engine


def _get_session_factory():
    """Get or create the session factory (lazy init)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


# Backward-compatible alias
def get_engine():
    """Get the async engine (creates on first call)."""
    return _get_engine()


def AsyncSessionLocal():
    """Create a new async session (backward-compatible callable)."""
    factory = _get_session_factory()
    return factory()


# ── Async context manager (preferred) ──

@asynccontextmanager
async def get_session():
    """Async context manager for database sessions with auto-commit/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_async_session():
    """FastAPI-compatible dependency that yields a session."""
    async with AsyncSessionLocal() as session:
        yield session


# ── Sync helpers (for Worker subprocess scripts) ──

_loop = None


def get_event_loop():
    """Get or create a persistent event loop for sync wrappers."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_sync(coro):
    """Run an async coroutine synchronously. For Worker scripts only."""
    loop = get_event_loop()
    return loop.run_until_complete(coro)


async def check_connection():
    """Verify database connectivity."""
    async with get_session() as session:
        await session.execute(text("SELECT 1"))
    return True


async def dispose_engine():
    """Close database engine and cleanup connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
