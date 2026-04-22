from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.enums import AssetType, GenerationMode, JobStatus


class JobCreate(BaseModel):
    project_id: str
    trend_source_id: str
    topic: str
    mode: GenerationMode = GenerationMode.REFERENCE_BASED
    duration_sec: int = Field(default=settings.DEFAULT_DURATION_SEC, ge=3, le=60)
    language: str = settings.DEFAULT_LANGUAGE
    target_platform: str = settings.DEFAULT_PLATFORM
    scene_count: int = Field(default=settings.DEFAULT_SCENE_COUNT, ge=2, le=8)
    template: str | None = None
    cta: str | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    enqueue: bool = False
    run_now: bool = False


class JobRunRequest(BaseModel):
    enqueue: bool = False
    resume: bool = False


class JobShotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shot_order: int
    shot_type: str
    duration_sec: float
    prompt: str
    camera: str
    motion: str
    overlay_text: str
    transition_name: str
    metadata_json: dict[str, Any]


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_type: AssetType
    path: str
    metadata_json: dict[str, Any]
    created_at: datetime


class LogEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage: str
    level: str
    message: str
    metadata_json: dict[str, Any]
    created_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    trend_source_id: str
    status: JobStatus
    mode: GenerationMode
    topic: str
    language: str
    target_platform: str
    duration_sec: int
    scene_count: int
    config_json: dict[str, Any]
    result_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobDetail(JobRead):
    shots: list[JobShotRead] = Field(default_factory=list)
    assets: list[AssetRead] = Field(default_factory=list)
    logs: list[LogEntryRead] = Field(default_factory=list)
