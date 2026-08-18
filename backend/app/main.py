"""FastAPI application entry point."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.problems import ProblemError, problem_handler

logging.basicConfig(level=logging.INFO)

settings = get_settings()

app = FastAPI(
    title="Bengaluru AI Property & Urban Intelligence Platform",
    version="0.1.0",
    description=(
        "Decision-support prototype for Greater Bengaluru. Every value returned "
        "carries its source, status and confidence. Missing data is reported as "
        "missing and is never substituted with a default."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.add_exception_handler(ProblemError, problem_handler)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
