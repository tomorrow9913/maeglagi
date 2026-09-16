from fastapi import APIRouter

from app.api.routes import auth, credentials, health, jobs, workspaces

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(workspaces.router, tags=["workspaces"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(credentials.router, tags=["provider-credentials"])
