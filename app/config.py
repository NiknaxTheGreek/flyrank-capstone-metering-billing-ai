"""Application configuration loaded from the runtime environment."""

import os
from dataclasses import dataclass
from urllib.parse import urlparse


class StripeConfigurationError(RuntimeError):
    """Raised when required Stripe test-mode configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class StripeTestSettings:
    """Validated environment-only settings for future Stripe test-mode work."""

    secret_key: str
    pro_price_id: str
    success_url: str
    cancel_url: str


def get_database_url() -> str:
    """Return the required SQLAlchemy database URL."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured.")
    return database_url


def get_stripe_test_settings() -> StripeTestSettings:
    """Return complete Stripe test-mode settings without exposing secret values."""
    secret_key = _required_environment_value("STRIPE_SECRET_KEY")
    if not secret_key.startswith("sk_test_"):
        raise StripeConfigurationError(
            "STRIPE_SECRET_KEY must be a Stripe test-mode secret key."
        )

    pro_price_id = _required_environment_value("STRIPE_PRO_PRICE_ID")
    if not pro_price_id.startswith("price_") or len(pro_price_id) <= len("price_"):
        raise StripeConfigurationError(
            "STRIPE_PRO_PRICE_ID must be a Stripe Price identifier beginning with 'price_'."
        )

    return StripeTestSettings(
        secret_key=secret_key,
        pro_price_id=pro_price_id,
        success_url=_validated_https_url("STRIPE_SUCCESS_URL"),
        cancel_url=_validated_https_url("STRIPE_CANCEL_URL"),
    )


def _required_environment_value(variable_name: str) -> str:
    """Return a non-empty runtime setting without including its value in errors."""
    value = os.getenv(variable_name)
    if not value:
        raise StripeConfigurationError(f"{variable_name} must be configured.")
    return value


def _validated_https_url(variable_name: str) -> str:
    """Return a safe absolute HTTPS redirect URL from environment configuration."""
    value = _required_environment_value(variable_name)
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise StripeConfigurationError(
            f"{variable_name} must be an absolute HTTPS URL without user credentials."
        )
    return value