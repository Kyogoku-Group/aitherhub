"""
AitherHub Shared Layer
======================
Common modules shared between API service and Worker service.
Both services import from here; neither imports from the other.

Architecture:
    aitherhub-api-service  ──→  shared  ←──  aitherhub-worker-service
    (backend/app/)                           (worker/)

Rules:
    1. shared/ MUST NOT import from backend/app/ or worker/
    2. backend/app/ MAY import from shared/
    3. worker/ MAY import from shared/
    4. backend/app/ MUST NOT import from worker/
    5. worker/ MUST NOT import from backend/app/
"""
