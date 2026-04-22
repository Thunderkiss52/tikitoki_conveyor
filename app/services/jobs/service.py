from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import Asset, Job, JobShot, LogEntry, Project, TrendSource
from app.schemas.job import JobCreate


DEFAULT_JOB_CONFIG = {
    "video_provider": settings.DEFAULT_VIDEO_PROVIDER,
    "tts_provider": settings.DEFAULT_TTS_PROVIDER,
    "music_provider": settings.DEFAULT_MUSIC_PROVIDER,
    "script_provider": settings.DEFAULT_SCRIPT_PROVIDER,
    "allow_synthetic_video": False,
    "brand_overlay": True,
    "subtitles": True,
    "voiceover": True,
    "music_mode": "hybrid",
}


class JobService:
    @staticmethod
    async def list(session: AsyncSession) -> list[Job]:
        result = await session.execute(select(Job).order_by(Job.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def get(session: AsyncSession, job_id: str) -> Job | None:
        return await session.get(Job, job_id)

    @staticmethod
    async def get_detail(session: AsyncSession, job_id: str) -> Job | None:
        result = await session.execute(
            select(Job)
            .where(Job.id == job_id)
            .execution_options(populate_existing=True)
            .options(
                selectinload(Job.project),
                selectinload(Job.trend_source),
                selectinload(Job.shots),
                selectinload(Job.assets),
                selectinload(Job.logs),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(session: AsyncSession, payload: JobCreate) -> Job:
        project = await session.get(Project, payload.project_id)
        if project is None:
            raise LookupError(f"Project not found: {payload.project_id}")

        trend_source = await session.get(TrendSource, payload.trend_source_id)
        if trend_source is None:
            raise LookupError(f"Trend source not found: {payload.trend_source_id}")

        config_json = {**DEFAULT_JOB_CONFIG, **payload.config_json}
        if payload.template:
            config_json["template"] = payload.template
        if payload.cta:
            config_json["cta"] = payload.cta

        job = Job(
            project_id=payload.project_id,
            trend_source_id=payload.trend_source_id,
            mode=payload.mode,
            topic=payload.topic,
            language=payload.language,
            target_platform=payload.target_platform,
            duration_sec=payload.duration_sec,
            scene_count=payload.scene_count,
            config_json=config_json,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

    @staticmethod
    async def clear_outputs(session: AsyncSession, job_id: str) -> None:
        await session.execute(delete(JobShot).where(JobShot.job_id == job_id))
        await session.execute(delete(Asset).where(Asset.job_id == job_id))
        await session.execute(delete(LogEntry).where(LogEntry.job_id == job_id))
        await session.commit()
