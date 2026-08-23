from fastapi import FastAPI

from app.api.checkout import router as checkout_router
from app.api.generate import router as generate_router
from app.api.health import router as health_router
from app.api.webhooks import router as webhook_router

app = FastAPI(title="FlyRank Usage Metering & Billing Engine")
app.include_router(health_router)
app.include_router(generate_router)
app.include_router(checkout_router)
app.include_router(webhook_router)