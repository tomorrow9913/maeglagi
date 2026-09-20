from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.workspaces.source_event_broker import SourceEventBroker
from app.core.config import Settings, get_settings
from app.mcp.server import create_mcp_server
from app.mcp.transport import ExactMCPRoute
from app.middleware import register_middlewares
from app.modules.ingestion.infrastructure.pg_executor import PostgresExecutor
from app.modules.retrieval.infrastructure.graph_store import Neo4jGraphStore


class CORSFastAPI(FastAPI):
    def __init__(self, *, cors_origins: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cors_origins = cors_origins

    def build_middleware_stack(self) -> CorrelationIdMiddleware:
        # CORS covers unhandled 500s; correlation also covers CORS preflights.
        return CorrelationIdMiddleware(
            CORSMiddleware(
                super().build_middleware_stack(),
                allow_origins=self.cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
                expose_headers=["X-Request-ID"],
            ),
            header_name="X-Request-ID",
        )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # Keep the async driver within this app's event loop and close it on shutdown.
    settings: Settings = application.state.settings
    # The SDK session manager is single-use. A fresh server and ASGI app are
    # required whenever the same FastAPI app enters another lifespan.
    mcp_server, mcp_app = create_mcp_server(settings)
    store = Neo4jGraphStore.from_settings(settings) if settings.neo4j_enabled else None
    application.state.graph_store = store
    executor = (
        PostgresExecutor(settings)
        if settings.processing_executor == "postgres" and settings.pg_executor_enabled
        else None
    )
    source_event_broker = SourceEventBroker(settings) if settings.source_events_enabled else None
    try:
        if source_event_broker is not None:
            await source_event_broker.start()
        application.state.source_event_broker = source_event_broker
        if executor is not None:
            executor.start()
        application.state.mcp_server = mcp_server
        application.state.mcp_route.app = mcp_app
        async with mcp_server.session_manager.run():
            yield
    finally:
        application.state.source_event_broker = None
        if source_event_broker is not None:
            await source_event_broker.stop()
        application.state.mcp_route.app = None
        application.state.mcp_server = None
        if executor is not None:
            await executor.stop()
        application.state.graph_store = None
        if store is not None:
            await store.close()


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
    application.state.settings = settings
    application.state.graph_store = None
    application.state.mcp_server = None
    application.state.source_event_broker = None
    register_middlewares(application, settings)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    mcp_route = ExactMCPRoute()
    application.state.mcp_route = mcp_route
    application.router.routes.append(mcp_route)
    return application


app = create_app()
