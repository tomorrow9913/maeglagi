from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.middleware import register_middlewares


class CORSFastAPI(FastAPI):
    def __init__(self, *, cors_origins: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cors_origins = cors_origins

    def build_middleware_stack(self) -> CORSMiddleware:
        # ServerErrorMiddleware produces unhandled 500s, so CORS must wrap it.
        return CORSMiddleware(
            super().build_middleware_stack(),
            allow_origins=self.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Initialize shared DB, queue, object, vector and graph clients here.
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    expose_api_docs = settings.app_env.lower() != "production"
    application = CORSFastAPI(
        cors_origins=settings.cors_origins,
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if expose_api_docs else None,
        redoc_url="/redoc" if expose_api_docs else None,
        openapi_url="/openapi.json" if expose_api_docs else None,
    )
    register_middlewares(application, settings)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
