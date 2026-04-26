"""
FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload
"""

from contextlib import asynccontextmanager

import posthog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import access_router
from api.config import settings as config_settings
from api.routes import calendars, google_auth, health, nudge, onboard, plan, replan, review, rhythms, settings, todoist_auth, today


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    posthog.shutdown()  # flush any queued events before process exits


app = FastAPI(title="schedule-for-me API", version="0.1.0", lifespan=lifespan)

_cors_origins = [o.strip() for o in config_settings.BACKEND_CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(google_auth.router)
app.include_router(calendars.router)
app.include_router(onboard.router)
app.include_router(plan.router)
app.include_router(rhythms.router)
app.include_router(todoist_auth.router)
app.include_router(today.router)
app.include_router(replan.router)
app.include_router(review.router)
app.include_router(settings.router)
app.include_router(nudge.router)
app.include_router(access_router)
