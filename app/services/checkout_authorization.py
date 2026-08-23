"""Tenant-bound HMAC proofs for the public tenant-scoped API endpoints."""

import hashlib
import hmac
import os
import uuid


class TenantAuthorizationError(Exception):
    """Raised when a request cannot prove authority for its stated tenant."""


class TenantAuthorizationNotConfiguredError(Exception):
    """Raised when the runtime has no signing secret for tenant authorization."""


def create_tenant_proof(
    tenant_id: uuid.UUID,
    signing_secret: str,
    *,
    audience: str,
) -> str:
    """Create an endpoint-bound proof for a trusted session or gateway to send."""
    message = f"{audience}:{tenant_id}".encode()
    return hmac.new(
        signing_secret.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()


def require_tenant_proof(
    tenant_id: uuid.UUID,
    provided_proof: str | None,
    *,
    audience: str,
) -> None:
    """Reject callers that cannot prove authority for the requested tenant."""
    signing_secret = os.getenv("SESSION_SECRET")
    if not signing_secret:
        raise TenantAuthorizationNotConfiguredError

    expected_proof = create_tenant_proof(
        tenant_id,
        signing_secret,
        audience=audience,
    )
    if not provided_proof or not hmac.compare_digest(provided_proof, expected_proof):
        raise TenantAuthorizationError


CheckoutAuthorizationError = TenantAuthorizationError
CheckoutAuthorizationNotConfiguredError = TenantAuthorizationNotConfiguredError


def create_checkout_tenant_proof(tenant_id: uuid.UUID, signing_secret: str) -> str:
    """Create the Checkout-specific proof retained for the existing endpoint."""
    return create_tenant_proof(tenant_id, signing_secret, audience="checkout")


def require_checkout_tenant_proof(
    tenant_id: uuid.UUID,
    provided_proof: str | None,
) -> None:
    """Require the Checkout-specific proof retained for the existing endpoint."""
    require_tenant_proof(tenant_id, provided_proof, audience="checkout")