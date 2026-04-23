from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.db.session import init_db
from app.utils.storage import ensure_base_storage


ensure_base_storage()
UI_DIR = Path(__file__).resolve().parent / "ui"


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

app.mount("/storage", StaticFiles(directory=settings.storage_root, check_dir=False), name="storage")
app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    return {
        "message": "Tikitoki Conveyor API is running",
        "version": "0.1.0",
        "api_prefix": settings.API_V1_STR,
        "docs": "/docs",
        "ui": "/ui/",
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}
