from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.enums import AssetType, GenerationMode, JobStatus, TrendSourceType
from app.core.ids import prefixed_id


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: prefixed_id("project"))
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    jobs: Mapped[list["Job"]] = relationship(back_populates="project")


class TrendSource(Base):
    __tablename__ = "trend_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: prefixed_id("trend"))
    type: Mapped[TrendSourceType] = mapped_column(SqlEnum(TrendSourceType), default=TrendSourceType.VIDEO)
    source_path: Mapped[str] = mapped_column(String(1024))
    hook_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    structure_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    jobs: Mapped[list["Job"]] = relationship(back_populates="trend_source")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: prefixed_id("job"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    trend_source_id: Mapped[str] = mapped_column(ForeignKey("trend_sources.id"), index=True)
    status: Mapped[JobStatus] = mapped_column(SqlEnum(JobStatus), default=JobStatus.QUEUED, index=True)
    mode: Mapped[GenerationMode] = mapped_column(
        SqlEnum(GenerationMode),
        default=GenerationMode.REFERENCE_BASED,
    )
    topic: Mapped[str] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(12), default="ru")
    target_platform: Mapped[str] = mapped_column(String(32), default="tiktok")
    duration_sec: Mapped[int] = mapped_column(Integer, default=8)
    scene_count: Mapped[int] = mapped_column(Integer, default=3)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="jobs")
    trend_source: Mapped["TrendSource"] = relationship(back_populates="jobs")
    shots: Mapped[list["JobShot"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobShot.shot_order",
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )
    logs: Mapped[list["LogEntry"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="LogEntry.created_at",
    )


class JobShot(Base):
    __tablename__ = "job_shots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: prefixed_id("shot"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    shot_order: Mapped[int] = mapped_column(Integer)
    shot_type: Mapped[str] = mapped_column(String(64))
    duration_sec: Mapped[float] = mapped_column()
    prompt: Mapped[str] = mapped_column(Text)
    camera: Mapped[str] = mapped_column(String(128), default="medium shot")
    motion: Mapped[str] = mapped_column(String(128), default="subtle motion")
    overlay_text: Mapped[str] = mapped_column(String(255), default="")
    transition_name: Mapped[str] = mapped_column(String(64), default="cut")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    job: Mapped["Job"] = relationship(back_populates="shots")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: prefixed_id("asset"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    asset_type: Mapped[AssetType] = mapped_column(SqlEnum(AssetType), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["Job"] = relationship(back_populates="assets")


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(32), default="info")
    message: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["Job"] = relationship(back_populates="logs")
