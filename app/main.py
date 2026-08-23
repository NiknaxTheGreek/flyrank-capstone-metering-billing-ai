from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(title="FlyRank Usage Metering & Billing Engine")
app.include_router(health_router)