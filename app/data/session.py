"""Request-scoped SQLAlchemy session dependency."""

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.data.database import create_database_engine


def get_session() -> Generator[Session, None, None]:
    """Yield a session for one API request and close its engine afterwards."""
    engine = create_database_engine()
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()