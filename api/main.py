"""
FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload

Routes:
    GET  /health                  — unauthenticated liveness check
    POST /api/onboard/stage1      — authenticated; calendar scan + LLM draft
"""

from fastapi import FastAPI

from api.routes import health, onboard

app = FastAPI(title="schedule-for-me API", version="0.1.0")

app.include_router(health.router)
app.include_router(onboard.router)
