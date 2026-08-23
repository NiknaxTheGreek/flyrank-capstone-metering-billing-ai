from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/healthz")
def read_health() -> dict[str, str]:
    """Return the service readiness signal."""
    return {"status": "ok"}