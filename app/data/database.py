"""SQLAlchemy engine and metadata configuration for the persistence layer."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import get_database_url
from app.data.models import Base

metadata = Base.metadata


def get_sqlalchemy_database_url() -> str:
    """Normalize PostgreSQL runtime URLs to the installed Psycopg 3 dialect."""
    database_url = get_database_url()
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def create_database_engine() -> Engine:
    """Create an engine from the runtime database URL."""
    return create_engine(get_sqlalchemy_database_url(), pool_pre_ping=True)


def verify_database_connection(engine: Engine) -> None:
    """Run a minimal PostgreSQL connectivity query."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))