"""Lazy Stripe SDK client construction for future test-mode API calls."""

from stripe import StripeClient

from app.config import StripeTestSettings, get_stripe_test_settings


def get_stripe_test_client(settings: StripeTestSettings | None = None) -> StripeClient:
    """Create a StripeClient from validated environment-only test settings."""
    resolved_settings = settings or get_stripe_test_settings()
    return StripeClient(resolved_settings.secret_key)