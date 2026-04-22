from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.trend import TrendSourceCreate, TrendSourceRead
from app.services.trends.service import TrendSourceService


router = APIRouter(prefix="/trends", tags=["trends"])


@router.get("", response_model=list[TrendSourceRead])
async def list_trends(session: AsyncSession = Depends(get_session)) -> list[TrendSourceRead]:
    return await TrendSourceService.list(session)


@router.post("", response_model=TrendSourceRead, status_code=status.HTTP_201_CREATED)
async def create_trend(
    payload: TrendSourceCreate,
    session: AsyncSession = Depends(get_session),
) -> TrendSourceRead:
    try:
        return await TrendSourceService.create(session, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/upload", response_model=TrendSourceRead, status_code=status.HTTP_201_CREATED)
async def upload_trend(
    file: UploadFile = File(...),
    hook_description: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> TrendSourceRead:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    return await TrendSourceService.create_upload(session, file.filename or "trend.mp4", content, hook_description)


@router.get("/{trend_id}", response_model=TrendSourceRead)
async def get_trend(trend_id: str, session: AsyncSession = Depends(get_session)) -> TrendSourceRead:
    trend_source = await TrendSourceService.get(session, trend_id)
    if trend_source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trend source not found")
    return trend_source
