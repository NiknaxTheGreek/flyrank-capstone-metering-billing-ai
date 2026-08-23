"""SQLAlchemy engine and metadata configuration for the persistence layer."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import get_database_url
from app.data.models import Base

metadata = Base.metadata


def create_database_engine() -> Engine:
    """Create an engine from the runtime database URL."""
    return create_engine(get_database_url(), pool_pre_ping=True)


def verify_database_connection(engine: Engine) -> None:
    """Run a minimal PostgreSQL connectivity query."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))