"""
AitherHub Worker Service
========================
Independent worker service for video/clip processing.

ABSOLUTE RULE: This package MUST NOT import from backend/app/.
All shared dependencies come from the shared/ package.

Start the worker:
    python -m worker.entrypoints.queue_worker
"""
