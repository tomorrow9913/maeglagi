from fastapi import FastAPI

from app.core.config import Settings
from app.middleware.cors import register_cors_middleware


def register_middlewares(application: FastAPI, settings: Settings) -> None:
    """Register cross-cutting middleware in one deterministic startup location."""

    register_cors_middleware(application, settings)
