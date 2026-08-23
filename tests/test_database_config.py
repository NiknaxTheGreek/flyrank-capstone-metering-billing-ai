import pytest

from app.config import get_database_url
from app.data.database import metadata


def test_database_url_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_url = "postgresql+psycopg://flyrank@localhost:5432/flyrank_metering"
    monkeypatch.setenv("DATABASE_URL", expected_url)

    assert get_database_url() == expected_url


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_database_url()


def test_metadata_has_no_domain_tables_yet() -> None:
    assert metadata.tables == {}