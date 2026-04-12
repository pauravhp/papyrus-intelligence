"""
FastAPI application entry point.

Start with:
    uvicorn api.main:app --reload

Routes:
    GET  /health                  — unauthenticated liveness check
    POST /api/onboard/stage1      — authenticated; calendar scan + LLM draft
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import chat, google_auth, health, onboard, plan

app = FastAPI(title="schedule-for-me API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(google_auth.router)
app.include_router(onboard.router)
app.include_router(plan.router)
app.include_router(chat.router)
