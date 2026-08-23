import pytest

from app.config import get_database_url
from app.data.database import get_sqlalchemy_database_url, metadata


def test_database_url_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_url = "postgresql+psycopg://flyrank@localhost:5432/flyrank_metering"
    monkeypatch.setenv("DATABASE_URL", expected_url)

    assert get_database_url() == expected_url


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_database_url()


def test_plain_postgresql_urls_use_the_installed_psycopg_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://flyrank@localhost:5432/metering")

    assert (
        get_sqlalchemy_database_url()
        == "postgresql+psycopg://flyrank@localhost:5432/metering"
    )


def test_metadata_collects_domain_tables() -> None:
    assert set(metadata.tables) == {
        "plans",
        "tenants",
        "subscriptions",
        "usage_events",
        "processed_webhook_events",
    }