from fastapi import APIRouter

from app.api import agent_uploads, ai, ask, auth, demo, jobs, mcp_tokens, system, workspaces

api_router = APIRouter()
api_router.include_router(agent_uploads.router)
api_router.include_router(mcp_tokens.router)
api_router.include_router(demo.router)
api_router.include_router(system.router, tags=["system"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(workspaces.router, tags=["workspaces"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(ask.router, tags=["ask"])
api_router.include_router(ai.router, tags=["ai-providers"])
api_router.include_router(ai.catalog_router, tags=["ai-providers"])
api_router.include_router(ai.models_router, tags=["ai-models"])
