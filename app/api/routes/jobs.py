import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.schemas.job import JobCreate, JobDetail, JobRead, JobRunRequest
from app.services.jobs import JobService, run_job_pipeline
from app.workers.queue import enqueue_job


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobRead])
async def list_jobs(session: AsyncSession = Depends(get_session)) -> list[JobRead]:
    return await JobService.list(session)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    session: AsyncSession = Depends(get_session),
) -> JobRead:
    try:
        job = await JobService.create(session, payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    job_id = job.id
    if payload.enqueue:
        try:
            enqueue_job(job_id)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    elif payload.run_now:
        await run_job_pipeline(job_id)
        session.expire_all()
        job = await JobService.get_detail(session, job_id)

    if job is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Job lost after creation")
    return job


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> JobDetail:
    job = await JobService.get_detail(session, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("/{job_id}/state")
async def get_job_state(job_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    job = await JobService.get(session, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    state_path = settings.jobs_root / job_id / "data" / "pipeline_state.json"
    if not state_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline state not found")

    return json.loads(state_path.read_text(encoding="utf-8"))


@router.post("/{job_id}/run", response_model=JobDetail)
async def run_job(
    job_id: str,
    payload: JobRunRequest,
    session: AsyncSession = Depends(get_session),
) -> JobDetail:
    job = await JobService.get(session, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if payload.enqueue:
        try:
            enqueue_job(job_id)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    else:
        await run_job_pipeline(job_id, resume=payload.resume)
        session.expire_all()

    refreshed = await JobService.get_detail(session, job_id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Job not available after run")
    return refreshed
