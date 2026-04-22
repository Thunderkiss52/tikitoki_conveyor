from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestResult(BaseModel):
    source_path: str
    frames: list[str] = Field(default_factory=list)
    source_meta: dict[str, Any] = Field(default_factory=dict)


class TrendAnalysis(BaseModel):
    hook: str
    beats: list[str] = Field(default_factory=list)
    estimated_scene_count: int = 3
    pace: str = "fast"
    camera_style: str = "static + close-up"
    mood: str = "comic contrast"
    references: dict[str, Any] = Field(default_factory=dict)


class ScriptPackage(BaseModel):
    title: str
    template: str
    voiceover: list[str] = Field(default_factory=list)
    overlays: list[str] = Field(default_factory=list)
    cta: str = ""


class ShotSpec(BaseModel):
    order: int
    duration_sec: float
    type: str
    prompt: str
    camera: str = "medium shot"
    motion: str = "slight handheld"
    overlay: str = ""
    transition: str = "cut"
    metadata: dict[str, Any] = Field(default_factory=dict)


class MediaArtifact(BaseModel):
    path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExportArtifacts(BaseModel):
    final_video: str
    subtitles: str
    voiceover_track: str | None = None
    music_track: str | None = None
    preview_image: str | None = None
    metadata_json: str


class ContentTemplate(BaseModel):
    name: str
    scene_roles: list[str] = Field(default_factory=list)
    mood: str
    prompt_style: str = ""
