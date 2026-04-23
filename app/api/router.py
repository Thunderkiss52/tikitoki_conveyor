from fastapi import APIRouter

from app.api.routes import health, jobs, projects, trends, ui


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(trends.router)
api_router.include_router(jobs.router)
api_router.include_router(ui.router)
