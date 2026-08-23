from app.api.health import read_health


def test_health_reports_ok() -> None:
    assert read_health() == {"status": "ok"}