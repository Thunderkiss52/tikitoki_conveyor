from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.db.session import init_db
from app.utils.storage import ensure_base_storage


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_base_storage()
    await init_db()
    yield

app = FastAPI(
    title="Tikitoki Conveyor API",
    description="Modular pipeline for automated video generation",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {
        "message": "Tikitoki Conveyor API is running",
        "version": "0.1.0",
        "api_prefix": settings.API_V1_STR,
        "docs": "/docs",
    }

@app.get("/health")
async def health_check():
    return {"status": "ok"}
