"""Application configuration loaded from the runtime environment."""

import os


def get_database_url() -> str:
    """Return the required SQLAlchemy database URL."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured.")
    return database_url