"""Dependency Injection Container (Legacy)

The project has migrated to async sessions via app.core.db.
This container is kept for backward compatibility but is effectively unused.
"""
from dependency_injector import containers, providers

from app.core.config import configs


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        modules=[
            # All endpoints use async pattern directly, no DI wiring needed
        ]
    )

    # Legacy DI bindings — not used in current async architecture
    # db = providers.Singleton(Database, db_url=configs.DATABASE_URI)
