"""
FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload
"""

from contextlib import asynccontextmanager

import posthog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import calendars, chat, google_auth, health, onboard, plan, replan, review, rhythms, todoist_auth, today


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    posthog.shutdown()  # flush any queued events before process exits


app = FastAPI(title="schedule-for-me API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(google_auth.router)
app.include_router(calendars.router)
app.include_router(onboard.router)
app.include_router(plan.router)
app.include_router(chat.router)
app.include_router(rhythms.router)
app.include_router(todoist_auth.router)
app.include_router(today.router)
app.include_router(replan.router)
app.include_router(review.router)
