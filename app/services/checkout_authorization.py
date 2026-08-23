"""Tenant-bound authorization proof for the public Checkout endpoint."""

import hashlib
import hmac
import os
import uuid


class CheckoutAuthorizationError(Exception):
    """Raised when a request cannot prove authority for its stated tenant."""


class CheckoutAuthorizationNotConfiguredError(Exception):
    """Raised when the runtime has no signing secret for tenant authorization."""


def create_checkout_tenant_proof(tenant_id: uuid.UUID, signing_secret: str) -> str:
    """Create a tenant-bound proof for a trusted session or gateway to send."""
    message = f"checkout:{tenant_id}".encode()
    return hmac.new(
        signing_secret.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


def require_checkout_tenant_proof(
    tenant_id: uuid.UUID,
    provided_proof: str | None,
) -> None:
    """Reject callers that cannot prove authority for the requested tenant."""
    signing_secret = os.getenv("SESSION_SECRET")
    if not signing_secret:
        raise CheckoutAuthorizationNotConfiguredError

    expected_proof = create_checkout_tenant_proof(tenant_id, signing_secret)
    if not provided_proof or not hmac.compare_digest(provided_proof, expected_proof):
        raise CheckoutAuthorizationError