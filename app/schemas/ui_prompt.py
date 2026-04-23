from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.enums import GenerationMode


class PromptChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=4000)


class PromptAssetSelection(BaseModel):
    images: list[str] = Field(default_factory=list)
    reference_video_path: str | None = None
    logo_path: str | None = None

    @field_validator("images")
    @classmethod
    def _dedupe_images(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        items: list[str] = []
        for item in value:
            candidate = item.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            items.append(candidate)
        return items


class PromptGenerationDraft(BaseModel):
    topic: str | None = None
    project_name: str | None = None
    hook_description: str | None = None
    cta: str | None = None
    duration_sec: int | None = Field(default=None, ge=3, le=60)
    scene_count: int | None = Field(default=None, ge=2, le=8)
    language: str | None = None
    target_platform: str | None = None
    aspect: str | None = None
    export_resolution: str | None = None
    title_override: str | None = None
    subtitles: bool | None = None
    voiceover: bool | None = None
    brand_overlay: bool | None = None
    generation_mode: str | None = None
    quality_preset: str | None = None
    safe_laptop_mode: bool | None = None


class SimplifiedShotOverride(BaseModel):
    order: int | None = None
    duration_sec: float = Field(ge=0.5, le=60)
    prompt: str = Field(min_length=1, max_length=1000)
    overlay: str = ""
    source_kind: str | None = None
    source_path: str | None = None
    source_start_sec: float | None = Field(default=None, ge=0.0)
    source_duration_sec: float | None = Field(default=None, ge=0.1)
    speed: float | None = Field(default=None, gt=0.0)
    reference_image_path: str | None = None
    reference_video_path: str | None = None
    camera: str | None = None
    motion: str | None = None
    transition: str | None = None


class PromptPlan(BaseModel):
    assistant_reply: str
    parser: Literal["openai", "fallback"]
    source_mode: Literal["reference_video", "image_sequence", "text_only"]
    mode: GenerationMode
    project_name: str
    topic: str
    hook_description: str
    cta: str | None = None
    duration_sec: int = Field(ge=3, le=60)
    scene_count: int = Field(ge=2, le=8)
    language: str = "ru"
    target_platform: str = "tiktok"
    aspect: str = "9:16"
    export_resolution: str | None = None
    template: str = "meme_problem_solution"
    visual_style: str = ""
    voice_style: str = "calm_dark_male"
    music_style: str = "dark cyber tension"
    title_override: str | None = None
    subtitles: bool = True
    voiceover: bool = True
    brand_overlay: bool = True
    overlay_lines: list[str] = Field(default_factory=list)
    voiceover_lines: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PromptPlanRequest(BaseModel):
    messages: list[PromptChatMessage] = Field(default_factory=list)
    assets: PromptAssetSelection = Field(default_factory=PromptAssetSelection)
    draft: PromptGenerationDraft = Field(default_factory=PromptGenerationDraft)


class PromptPlanResponse(BaseModel):
    plan: PromptPlan
    openai_configured: bool
    model: str | None = None


class PromptGenerateRequest(BaseModel):
    plan: PromptPlan | None = None
    assets: PromptAssetSelection = Field(default_factory=PromptAssetSelection)
    draft: PromptGenerationDraft = Field(default_factory=PromptGenerationDraft)
    shot_overrides: list[SimplifiedShotOverride] = Field(default_factory=list)
    enqueue: bool = False
    run_now: bool = True
