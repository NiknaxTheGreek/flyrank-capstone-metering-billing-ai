import pytest
from stripe import StripeClient

from app.config import (
    StripeConfigurationError,
    get_stripe_test_settings,
    get_stripe_webhook_settings,
)
from app.integrations.stripe.client import get_stripe_test_client


def _set_valid_stripe_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example_key")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_test_example")
    monkeypatch.setenv(
        "STRIPE_SUCCESS_URL",
        "https://example.test/billing/success?session_id={CHECKOUT_SESSION_ID}",
    )
    monkeypatch.setenv("STRIPE_CANCEL_URL", "https://example.test/billing/cancel")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_signing_secret")


def test_stripe_test_settings_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_stripe_environment(monkeypatch)

    settings = get_stripe_test_settings()

    assert settings.secret_key == "sk_test_example_key"
    assert settings.pro_price_id == "price_test_example"
    assert settings.success_url.startswith("https://")
    assert settings.cancel_url.startswith("https://")


def test_stripe_client_uses_validated_test_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_valid_stripe_environment(monkeypatch)

    client = get_stripe_test_client()

    assert isinstance(client, StripeClient)


def test_stripe_webhook_settings_use_runtime_secret_and_configured_pro_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_valid_stripe_environment(monkeypatch)

    settings = get_stripe_webhook_settings()

    assert settings.signing_secret == "whsec_test_signing_secret"
    assert settings.pro_price_id == "price_test_example"


@pytest.mark.parametrize(
    ("variable_name", "value", "message"),
    [
        ("STRIPE_SECRET_KEY", None, "STRIPE_SECRET_KEY"),
        ("STRIPE_SECRET_KEY", "sk_live_not_allowed", "test-mode"),
        ("STRIPE_PRO_PRICE_ID", "prod_not_a_price", "price_"),
        ("STRIPE_SUCCESS_URL", "http://example.test/success", "HTTPS"),
        ("STRIPE_CANCEL_URL", "https://user:pass@example.test/cancel", "HTTPS"),
    ],
)
def test_stripe_test_settings_reject_unsafe_or_incomplete_values(
    monkeypatch: pytest.MonkeyPatch,
    variable_name: str,
    value: str | None,
    message: str,
) -> None:
    _set_valid_stripe_environment(monkeypatch)
    if value is None:
        monkeypatch.delenv(variable_name)
    else:
        monkeypatch.setenv(variable_name, value)

    with pytest.raises(StripeConfigurationError, match=message):
        get_stripe_test_settings()


@pytest.mark.parametrize(
    ("variable_name", "value", "message"),
    [
        ("STRIPE_WEBHOOK_SECRET", None, "STRIPE_WEBHOOK_SECRET"),
        ("STRIPE_WEBHOOK_SECRET", "not_a_signing_secret", "whsec_"),
        ("STRIPE_PRO_PRICE_ID", "not_a_price", "price_"),
    ],
)
def test_stripe_webhook_settings_reject_unsafe_or_incomplete_values(
    monkeypatch: pytest.MonkeyPatch,
    variable_name: str,
    value: str | None,
    message: str,
) -> None:
    _set_valid_stripe_environment(monkeypatch)
    if value is None:
        monkeypatch.delenv(variable_name)
    else:
        monkeypatch.setenv(variable_name, value)

    with pytest.raises(StripeConfigurationError, match=message):
        get_stripe_webhook_settings()