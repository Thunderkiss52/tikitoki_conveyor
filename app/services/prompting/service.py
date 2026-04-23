from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.enums import GenerationMode, TrendSourceType
from app.providers.llm.template import TemplateScriptProvider
from app.schemas.ui_prompt import (
    PromptAssetSelection,
    PromptGenerationDraft,
    PromptPlan,
    PromptPlanRequest,
    PromptPlanResponse,
    SimplifiedShotOverride,
)
from app.utils.media import ffprobe_media
from app.utils.storage import resolve_local_path, safe_slug


class _LLMPromptPlan(BaseModel):
    assistant_reply: str = Field(description="Short reply for the UI chat.")
    project_name: str = Field(description="Short campaign or brand name.")
    topic: str = Field(description="Main topic of the video.")
    hook_description: str = Field(description="What happens in the hook or first seconds.")
    cta: str | None = Field(default=None, description="Call to action if the user mentioned one.")
    duration_sec: int = Field(default=settings.DEFAULT_DURATION_SEC)
    scene_count: int = Field(default=settings.DEFAULT_SCENE_COUNT)
    language: str = Field(default=settings.DEFAULT_LANGUAGE, description="Output language, usually ru or en.")
    target_platform: str = Field(default=settings.DEFAULT_PLATFORM)
    aspect: str = Field(default=settings.DEFAULT_ASPECT, description="One of 9:16, 16:9, 1:1.")
    export_resolution: str | None = Field(default=None, description="Optional WIDTHxHEIGHT resolution override.")
    template: str = Field(
        default="meme_problem_solution",
        description=(
            "Content template. Use only one of: meme_problem_solution, dark_cinematic, "
            "funny_pet_contrast, problem_solution_cta, fandom_reveal_parody."
        ),
    )
    visual_style: str = Field(default="clean vertical short")
    voice_style: str = Field(default="calm_dark_male")
    music_style: str = Field(default="dark cyber tension")
    title_override: str | None = None
    subtitles: bool = True
    voiceover: bool = True
    brand_overlay: bool = True
    overlay_lines: list[str] = Field(default_factory=list)
    voiceover_lines: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PromptPlanningService:
    def __init__(self) -> None:
        self.template_provider = TemplateScriptProvider()
        self.template_names = tuple(self.template_provider.templates.keys())

    def plan(self, payload: PromptPlanRequest) -> PromptPlanResponse:
        source_mode = self.resolve_source_mode(payload.assets)
        if settings.OPENAI_API_KEY:
            try:
                candidate = self._plan_with_openai(payload, source_mode)
                parser = "openai"
            except Exception as exc:
                candidate = self._fallback_plan(payload, source_mode, str(exc))
                parser = "fallback"
        else:
            candidate = self._fallback_plan(payload, source_mode, None)
            parser = "fallback"

        plan = self._normalize_candidate(candidate, payload, parser=parser, source_mode=source_mode)
        return PromptPlanResponse(
            plan=plan,
            openai_configured=bool(settings.OPENAI_API_KEY),
            model=settings.OPENAI_PROMPT_MODEL if settings.OPENAI_API_KEY else None,
        )

    def apply_draft_overrides(
        self,
        plan: PromptPlan,
        draft: PromptGenerationDraft,
        assets: PromptAssetSelection,
    ) -> PromptPlan:
        updated = plan.model_copy(deep=True)
        source_mode = self.resolve_source_mode(assets)

        if draft.project_name:
            updated.project_name = draft.project_name.strip()
        if draft.topic:
            updated.topic = draft.topic.strip()
        if draft.hook_description:
            updated.hook_description = draft.hook_description.strip()
        if draft.cta is not None:
            updated.cta = draft.cta.strip() or None
        if draft.duration_sec is not None:
            updated.duration_sec = self._clamp_int(draft.duration_sec, 3, 60, settings.DEFAULT_DURATION_SEC)
        if draft.scene_count is not None:
            updated.scene_count = self._clamp_int(draft.scene_count, 2, 8, self._scene_count_for_duration(updated.duration_sec))
        if draft.language:
            updated.language = draft.language.strip() or settings.DEFAULT_LANGUAGE
        if draft.target_platform:
            updated.target_platform = draft.target_platform.strip() or settings.DEFAULT_PLATFORM
        if draft.aspect:
            updated.aspect = self._normalize_aspect(draft.aspect)
        if draft.export_resolution is not None:
            updated.export_resolution = draft.export_resolution.strip() or None
        if draft.title_override is not None:
            updated.title_override = draft.title_override.strip() or None
        if draft.subtitles is not None:
            updated.subtitles = bool(draft.subtitles)
        if draft.voiceover is not None:
            updated.voiceover = bool(draft.voiceover)
        if draft.brand_overlay is not None:
            updated.brand_overlay = bool(draft.brand_overlay)

        updated.source_mode = source_mode
        updated.mode = self._mode_for_source_mode(source_mode)
        updated.brand_overlay = bool(updated.brand_overlay and assets.logo_path)
        updated.template = self._normalize_template(updated.template, updated.topic, updated.hook_description, updated.visual_style)
        updated.project_name = self._clean_project_name(updated.project_name, updated.topic)
        updated.voice_style = updated.voice_style.strip() or "calm_dark_male"
        updated.music_style = updated.music_style.strip() or "dark cyber tension"
        updated.visual_style = updated.visual_style.strip() or "clean vertical short"
        updated.overlay_lines = self._fit_lines(updated.overlay_lines, updated.scene_count)
        updated.voiceover_lines = self._fit_lines(updated.voiceover_lines, updated.scene_count)
        updated = self._fill_script_lines(updated)

        notes = list(updated.notes)
        if assets.logo_path is None and updated.brand_overlay:
            updated.brand_overlay = False
        if assets.logo_path is None:
            notes.append("Логотип не выбран, поэтому brand overlay отключен.")
        updated.notes = self._dedupe_notes(notes)
        return updated

    def build_shot_overrides(
        self,
        plan: PromptPlan,
        assets: PromptAssetSelection,
        manual_overrides: list[SimplifiedShotOverride],
    ) -> list[dict[str, Any]]:
        if manual_overrides:
            return self._manual_shot_overrides(plan, assets, manual_overrides)
        if assets.reference_video_path and assets.images:
            return self._mixed_reference_and_images(plan, assets)
        if assets.images:
            return self._image_sequence_shots(plan, assets)
        return []

    def build_prompt_inputs(self, plan: PromptPlan, assets: PromptAssetSelection) -> dict[str, Any]:
        return {
            "images": list(assets.images),
            "reference_video_path": assets.reference_video_path,
            "logo_path": assets.logo_path,
            "source_mode": plan.source_mode,
            "parser": plan.parser,
        }

    def create_project_payload(self, plan: PromptPlan, assets: PromptAssetSelection) -> dict[str, Any]:
        return {
            "name": plan.project_name,
            "config": {
                "logo_path": assets.logo_path,
                "brand_colors": ["#0F172A", "#14B8A6", "#F59E0B"],
                "voice_style": plan.voice_style,
                "music_style": plan.music_style,
                "default_aspect": plan.aspect,
                "extra": {
                    "visual_style": plan.visual_style,
                    "source_mode": plan.source_mode,
                },
            },
        }

    def create_trend_payload(self, plan: PromptPlan, assets: PromptAssetSelection) -> dict[str, Any]:
        if assets.reference_video_path:
            return {
                "type": TrendSourceType.VIDEO,
                "source_path": assets.reference_video_path,
                "hook_description": plan.hook_description,
                "structure_detected": False,
                "metadata_json": {
                    "source_mode": plan.source_mode,
                },
            }
        return {
            "type": TrendSourceType.TEXT,
            "source_path": plan.topic,
            "hook_description": plan.hook_description,
            "structure_detected": False,
            "metadata_json": {
                "source_mode": plan.source_mode,
                "images": list(assets.images),
            },
        }

    def create_job_payload(
        self,
        plan: PromptPlan,
        assets: PromptAssetSelection,
        project_id: str,
        trend_source_id: str,
        shot_overrides: list[dict[str, Any]],
        enqueue: bool,
        run_now: bool,
    ) -> dict[str, Any]:
        video_provider = self._video_provider_for_assets(assets)
        config_json: dict[str, Any] = {
            "video_provider": video_provider,
            "tts_provider": settings.DEFAULT_TTS_PROVIDER,
            "music_provider": settings.DEFAULT_MUSIC_PROVIDER,
            "script_provider": settings.DEFAULT_SCRIPT_PROVIDER,
            "allow_synthetic_video": video_provider in {"stub", "synthetic"},
            "brand_overlay": bool(plan.brand_overlay and assets.logo_path),
            "subtitles": plan.subtitles,
            "voiceover": plan.voiceover,
            "music_mode": "library",
            "quality_preset": "high",
            "aspect": plan.aspect,
            "export_resolution": plan.export_resolution or "",
            "template": plan.template,
            "cta": plan.cta,
            "title_override": plan.title_override,
            "overlay_lines": list(plan.overlay_lines),
            "voiceover_lines": list(plan.voiceover_lines),
            "prompt_plan": plan.model_dump(mode="json"),
            "prompt_inputs": self.build_prompt_inputs(plan, assets),
        }
        if shot_overrides:
            config_json["shot_overrides"] = shot_overrides

        return {
            "project_id": project_id,
            "trend_source_id": trend_source_id,
            "topic": plan.topic,
            "mode": plan.mode,
            "duration_sec": plan.duration_sec,
            "language": plan.language,
            "target_platform": plan.target_platform,
            "scene_count": plan.scene_count,
            "template": plan.template,
            "cta": plan.cta,
            "config_json": config_json,
            "enqueue": enqueue,
            "run_now": run_now,
        }

    def resolve_source_mode(self, assets: PromptAssetSelection) -> str:
        if assets.reference_video_path:
            return "reference_video"
        if assets.images:
            return "image_sequence"
        return "text_only"

    def ensure_asset_exists(self, raw_path: str) -> str:
        path = resolve_local_path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"Asset not found: {path}")
        return str(path)

    def _plan_with_openai(self, payload: PromptPlanRequest, source_mode: str) -> _LLMPromptPlan:
        input_messages = [
            {
                "role": "system",
                "content": self._system_prompt(source_mode),
            },
            {
                "role": "user",
                "content": self._context_summary(payload, source_mode),
            },
            *[
                {"role": message.role, "content": message.content}
                for message in payload.messages[-12:]
            ],
        ]

        request_payload: dict[str, Any] = {
            "model": settings.OPENAI_PROMPT_MODEL,
            "input": input_messages,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "prompt_generation_plan",
                    "schema": _LLMPromptPlan.model_json_schema(),
                    "strict": False,
                },
            },
        }
        if settings.OPENAI_PROMPT_MODEL.startswith("gpt-5"):
            request_payload["reasoning"] = {"effort": settings.OPENAI_PROMPT_REASONING_EFFORT}

        base_url = (settings.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        response = httpx.post(
            f"{base_url}/responses",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=settings.OPENAI_PROMPT_TIMEOUT_SEC,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI planner request failed with HTTP {response.status_code}: {response.text[:500]}")

        output_text = self._extract_openai_output_text(response.json())
        if not output_text:
            raise RuntimeError("OpenAI prompt planner returned no output_text.")
        return _LLMPromptPlan.model_validate_json(output_text)

    def _extract_openai_output_text(self, response_payload: dict[str, Any]) -> str:
        output_items = response_payload.get("output") or []
        for item in output_items:
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                if content.get("type") == "output_text":
                    return str(content.get("text") or "")
        return ""

    def _system_prompt(self, source_mode: str) -> str:
        return (
            "You are a video generation parameter planner for a local Docker UI. "
            "Return only structured data that maps a user's prompt to video generation parameters. "
            f"Current source mode is {source_mode}. "
            "If there is a reference video, keep motion close to the reference. "
            "If there are images but no reference video, plan for image-sequence video generation. "
            "If there are no visual assets, plan a text-only generation setup. "
            "Keep the reply concise, practical, and in the user's language. "
            f"Use only these templates: {', '.join(self.template_names)}. "
            "Use aspect only from: 9:16, 16:9, 1:1. "
            "Do not invent unsupported tracking or VFX behavior."
        )

    def _context_summary(self, payload: PromptPlanRequest, source_mode: str) -> str:
        draft = payload.draft.model_dump(mode="json")
        return (
            "Context for planning:\n"
            f"- source_mode: {source_mode}\n"
            f"- image_count: {len(payload.assets.images)}\n"
            f"- has_reference_video: {bool(payload.assets.reference_video_path)}\n"
            f"- has_logo: {bool(payload.assets.logo_path)}\n"
            f"- current_draft_defaults: {draft}\n"
            "Map the user's prompt to a workable plan for this UI."
        )

    def _fallback_plan(self, payload: PromptPlanRequest, source_mode: str, error_text: str | None) -> _LLMPromptPlan:
        prompt_text = self._latest_user_text(payload) or payload.draft.topic or "promo video"
        duration = payload.draft.duration_sec or self._detect_duration(prompt_text) or settings.DEFAULT_DURATION_SEC
        topic = (payload.draft.topic or prompt_text).strip()
        hook_description = (payload.draft.hook_description or topic).strip()
        project_name = payload.draft.project_name or self._clean_project_name("", topic)
        scene_count = payload.draft.scene_count or self._scene_count_for_duration(duration)
        language = (payload.draft.language or self._detect_language(prompt_text) or settings.DEFAULT_LANGUAGE).strip()
        cta = payload.draft.cta or self._detect_cta(prompt_text, language)
        aspect = self._normalize_aspect(payload.draft.aspect or settings.DEFAULT_ASPECT)
        template = self._normalize_template("", topic, hook_description, prompt_text)
        script = self.template_provider.generate_script(
            {
                "project_name": project_name,
                "topic": topic,
                "scene_count": scene_count,
                "template": template,
                "cta": cta,
                "language": language,
                "analysis": {
                    "hook": hook_description,
                    "mood": prompt_text,
                },
            }
        )

        notes = []
        if error_text:
            notes.append(f"OpenAI parser is unavailable, fallback parsing used: {error_text}")
        if source_mode == "text_only":
            notes.append("Нет референс-видео и картинок, поэтому будет использован text-only video path.")
        elif source_mode == "image_sequence":
            notes.append("Референс-видео не выбрано, поэтому картинки будут собраны в image-sequence video.")
        else:
            notes.append("Референс-видео будет использоваться как основа движения.")

        return _LLMPromptPlan(
            assistant_reply=self._fallback_reply(source_mode, topic, payload.assets.logo_path is not None, language),
            project_name=project_name,
            topic=topic,
            hook_description=hook_description,
            cta=cta,
            duration_sec=duration,
            scene_count=scene_count,
            language=language,
            target_platform=payload.draft.target_platform or settings.DEFAULT_PLATFORM,
            aspect=aspect,
            export_resolution=payload.draft.export_resolution,
            template=template,
            visual_style=self._visual_style(prompt_text, source_mode),
            voice_style="calm_dark_male" if language == "ru" else "clear_direct",
            music_style="dark cyber tension" if "dark" in prompt_text.lower() else "clean branded pulse",
            title_override=payload.draft.title_override,
            subtitles=payload.draft.subtitles if payload.draft.subtitles is not None else True,
            voiceover=payload.draft.voiceover if payload.draft.voiceover is not None else True,
            brand_overlay=payload.draft.brand_overlay if payload.draft.brand_overlay is not None else True,
            overlay_lines=script.overlays,
            voiceover_lines=script.voiceover,
            notes=notes,
        )

    def _normalize_candidate(
        self,
        candidate: _LLMPromptPlan,
        payload: PromptPlanRequest,
        parser: str,
        source_mode: str,
    ) -> PromptPlan:
        duration = self._clamp_int(candidate.duration_sec, 3, 60, settings.DEFAULT_DURATION_SEC)
        scene_count = self._clamp_int(candidate.scene_count, 2, 8, self._scene_count_for_duration(duration))
        topic = (payload.draft.topic or candidate.topic or self._latest_user_text(payload) or "promo video").strip()
        project_name = self._clean_project_name(payload.draft.project_name or candidate.project_name, topic)
        hook_description = (payload.draft.hook_description or candidate.hook_description or topic).strip()
        template = self._normalize_template(candidate.template, topic, hook_description, candidate.visual_style)
        language = (payload.draft.language or candidate.language or settings.DEFAULT_LANGUAGE).strip() or settings.DEFAULT_LANGUAGE
        target_platform = (
            payload.draft.target_platform
            or candidate.target_platform
            or settings.DEFAULT_PLATFORM
        ).strip() or settings.DEFAULT_PLATFORM
        aspect = self._normalize_aspect(payload.draft.aspect or candidate.aspect)
        export_resolution = payload.draft.export_resolution if payload.draft.export_resolution is not None else candidate.export_resolution
        title_override = payload.draft.title_override if payload.draft.title_override is not None else candidate.title_override
        cta = payload.draft.cta if payload.draft.cta is not None else candidate.cta
        brand_overlay = bool((payload.draft.brand_overlay if payload.draft.brand_overlay is not None else candidate.brand_overlay) and payload.assets.logo_path)
        subtitles = bool(payload.draft.subtitles if payload.draft.subtitles is not None else candidate.subtitles)
        voiceover = bool(payload.draft.voiceover if payload.draft.voiceover is not None else candidate.voiceover)

        plan = PromptPlan(
            assistant_reply=candidate.assistant_reply.strip() or self._fallback_reply(source_mode, topic, payload.assets.logo_path is not None, language),
            parser=parser,
            source_mode=source_mode,  # type: ignore[arg-type]
            mode=self._mode_for_source_mode(source_mode),
            project_name=project_name,
            topic=topic,
            hook_description=hook_description,
            cta=cta.strip() if isinstance(cta, str) and cta.strip() else None,
            duration_sec=duration,
            scene_count=scene_count,
            language=language,
            target_platform=target_platform,
            aspect=aspect,
            export_resolution=export_resolution.strip() if isinstance(export_resolution, str) and export_resolution.strip() else None,
            template=template,
            visual_style=candidate.visual_style.strip() or self._visual_style(topic, source_mode),
            voice_style=candidate.voice_style.strip() or "calm_dark_male",
            music_style=candidate.music_style.strip() or "dark cyber tension",
            title_override=title_override.strip() if isinstance(title_override, str) and title_override.strip() else None,
            subtitles=subtitles,
            voiceover=voiceover,
            brand_overlay=brand_overlay,
            overlay_lines=self._fit_lines(candidate.overlay_lines, scene_count),
            voiceover_lines=self._fit_lines(candidate.voiceover_lines, scene_count),
            notes=self._dedupe_notes(candidate.notes),
        )
        return self._fill_script_lines(plan)

    def _fill_script_lines(self, plan: PromptPlan) -> PromptPlan:
        script = self.template_provider.generate_script(
            {
                "project_name": plan.project_name,
                "topic": plan.topic,
                "scene_count": plan.scene_count,
                "template": plan.template,
                "cta": plan.cta,
                "language": plan.language,
                "analysis": {
                    "hook": plan.hook_description,
                    "mood": plan.visual_style,
                },
            }
        )
        overlays = self._merge_lines(plan.overlay_lines, script.overlays, plan.scene_count)
        voiceover = self._merge_lines(plan.voiceover_lines, script.voiceover, plan.scene_count)
        return plan.model_copy(update={"overlay_lines": overlays, "voiceover_lines": voiceover})

    def _manual_shot_overrides(
        self,
        plan: PromptPlan,
        assets: PromptAssetSelection,
        overrides: list[SimplifiedShotOverride],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        fallback_images = list(assets.images)
        for index, override in enumerate(overrides, start=1):
            provider_settings: dict[str, Any] = {}
            source_kind = (override.source_kind or "").strip()
            source_path = override.source_path or None
            reference_image_path = override.reference_image_path or None
            reference_video_path = override.reference_video_path or None

            if not source_kind:
                if reference_video_path or source_path or assets.reference_video_path:
                    source_kind = "video"
                elif reference_image_path or source_path or fallback_images:
                    source_kind = "image_to_video"
                else:
                    source_kind = "generated"

            if source_kind == "video" and not source_path and not reference_video_path and assets.reference_video_path:
                source_path = assets.reference_video_path
                reference_video_path = assets.reference_video_path
            if source_kind in {"image", "image_to_video", "brand"} and not source_path and not reference_image_path and fallback_images:
                source_path = fallback_images[(index - 1) % len(fallback_images)]
                reference_image_path = source_path

            if source_kind and source_kind != "generated":
                provider_settings["source_kind"] = source_kind
            if source_path and source_kind != "generated":
                provider_settings["source_path"] = source_path
            if reference_image_path:
                provider_settings["reference_image_path"] = reference_image_path
            if reference_video_path:
                provider_settings["reference_video_path"] = reference_video_path
            if override.source_start_sec is not None:
                provider_settings["source_start_sec"] = override.source_start_sec
            if override.source_duration_sec is not None:
                provider_settings["source_duration_sec"] = override.source_duration_sec
            if override.speed is not None:
                provider_settings["speed"] = override.speed

            items.append(
                {
                    "type": f"scene_{index}",
                    "duration_sec": float(override.duration_sec),
                    "prompt": override.prompt.strip(),
                    "overlay": override.overlay.strip(),
                    "camera": override.camera or ("close-up" if index == 1 else "medium shot"),
                    "motion": override.motion or ("slow push-in" if source_kind.startswith("image") else "slight handheld"),
                    "transition": override.transition or "cut",
                    "provider_settings": provider_settings,
                }
            )
        return items

    def _image_sequence_shots(self, plan: PromptPlan, assets: PromptAssetSelection) -> list[dict[str, Any]]:
        image_paths = list(assets.images)
        if not image_paths:
            return []
        durations = self._split_duration(plan.duration_sec, plan.scene_count)
        items: list[dict[str, Any]] = []
        for index in range(plan.scene_count):
            image_path = image_paths[index % len(image_paths)]
            items.append(
                {
                    "type": f"image_scene_{index + 1}",
                    "duration_sec": durations[index],
                    "prompt": self._shot_prompt(plan, index),
                    "overlay": self._line_for_index(plan.overlay_lines, index, plan.project_name),
                    "camera": "close-up" if index == 0 else "medium shot",
                    "motion": "slow push-in",
                    "transition": "cut",
                    "provider_settings": {
                        "source_kind": "image_to_video",
                        "source_path": image_path,
                        "reference_image_path": image_path,
                        "fade_in_sec": 0.18 if index == 0 else 0.0,
                        "fade_out_sec": 0.18 if index == plan.scene_count - 1 else 0.0,
                        "image_scale": 0.72,
                        "zoom_end": 1.08,
                    },
                }
            )
        return items

    def _mixed_reference_and_images(self, plan: PromptPlan, assets: PromptAssetSelection) -> list[dict[str, Any]]:
        if not assets.reference_video_path or not assets.images:
            return []
        if plan.scene_count < 2:
            return []

        reference_duration = self._reference_duration(assets.reference_video_path) or float(plan.duration_sec)
        final_image_duration = min(max(round(plan.duration_sec * 0.25, 2), 2.0), 4.0)
        video_total_duration = max(round(plan.duration_sec - final_image_duration, 2), 1.0)
        video_scene_count = max(plan.scene_count - 1, 1)
        video_output_durations = self._split_duration(video_total_duration, video_scene_count)
        source_slice_durations = self._split_duration(reference_duration, video_scene_count)

        items: list[dict[str, Any]] = []
        source_cursor = 0.0
        for index in range(video_scene_count):
            source_duration = max(round(source_slice_durations[index], 2), 0.5)
            items.append(
                {
                    "type": f"reference_scene_{index + 1}",
                    "duration_sec": video_output_durations[index],
                    "prompt": self._shot_prompt(plan, index),
                    "overlay": self._line_for_index(plan.overlay_lines, index, plan.project_name),
                    "camera": "close-up" if index == 0 else "medium shot",
                    "motion": "slight handheld",
                    "transition": "cut",
                    "provider_settings": {
                        "source_kind": "video",
                        "source_path": assets.reference_video_path,
                        "reference_video_path": assets.reference_video_path,
                        "source_start_sec": round(source_cursor, 2),
                        "source_duration_sec": source_duration,
                        "speed": 1.0,
                        "punch_in": 1.04 if index == 0 else 1.08,
                    },
                }
            )
            source_cursor = min(round(source_cursor + source_duration, 2), reference_duration)

        reveal_image = assets.images[0]
        items.append(
            {
                "type": "image_reveal",
                "duration_sec": final_image_duration,
                "prompt": self._shot_prompt(plan, plan.scene_count - 1),
                "overlay": self._line_for_index(plan.overlay_lines, plan.scene_count - 1, plan.project_name),
                "camera": "medium shot",
                "motion": "slow push-in",
                "transition": "fade",
                "provider_settings": {
                    "source_kind": "image_to_video",
                    "source_path": reveal_image,
                    "reference_image_path": reveal_image,
                    "fade_in_sec": 0.12,
                    "fade_out_sec": 0.18,
                    "image_scale": 0.68,
                    "zoom_end": 1.1,
                },
            }
        )
        return items

    def _reference_duration(self, raw_path: str) -> float | None:
        try:
            meta = ffprobe_media(resolve_local_path(raw_path))
        except Exception:
            return None
        duration = meta.get("duration_sec")
        if duration is None:
            return None
        try:
            return float(duration)
        except (TypeError, ValueError):
            return None

    def _shot_prompt(self, plan: PromptPlan, index: int) -> str:
        voice_line = self._line_for_index(plan.voiceover_lines, index, plan.topic)
        return f"{plan.topic}, {plan.visual_style}, {voice_line}".strip(", ")

    def _video_provider_for_assets(self, assets: PromptAssetSelection) -> str:
        if assets.reference_video_path or assets.images:
            return "reference"
        return settings.TEXT_ONLY_VIDEO_PROVIDER

    def _line_for_index(self, lines: list[str], index: int, fallback: str) -> str:
        if 0 <= index < len(lines) and lines[index].strip():
            return lines[index].strip()
        return fallback

    def _latest_user_text(self, payload: PromptPlanRequest) -> str:
        for message in reversed(payload.messages):
            if message.role == "user" and message.content.strip():
                return message.content.strip()
        return ""

    def _clean_project_name(self, value: str, topic: str) -> str:
        base = (value or "").strip()
        if base:
            return base[:80]
        words = [word for word in re.split(r"\s+", topic.strip()) if word]
        short = " ".join(words[:4]).strip()
        return short[:80] or "Prompt Studio"

    def _detect_duration(self, prompt_text: str) -> int | None:
        match = re.search(r"(\d{1,2})\s*(?:сек|секунд|seconds|second|sec|s)\b", prompt_text.lower())
        if not match:
            return None
        return int(match.group(1))

    def _detect_language(self, prompt_text: str) -> str | None:
        if re.search(r"[а-яА-Я]", prompt_text):
            return "ru"
        if prompt_text.strip():
            return "en"
        return None

    def _detect_cta(self, prompt_text: str, language: str) -> str:
        lowered = prompt_text.lower()
        if "подпиш" in lowered:
            return "Подписывайся"
        if "напиши" in lowered:
            return "Напиши в личку"
        if "куп" in lowered:
            return "Закажи сейчас"
        return "Ссылка в профиле" if language == "ru" else "Link in bio"

    def _visual_style(self, prompt_text: str, source_mode: str) -> str:
        lowered = prompt_text.lower()
        if any(token in lowered for token in ("dark", "cyber", "noir", "cinematic", "тём", "мрач")):
            return "dark cinematic vertical short"
        if source_mode == "image_sequence":
            return "clean product montage from still images"
        if source_mode == "text_only":
            return "simple generated vertical short"
        return "fast social vertical short"

    def _normalize_template(self, template: str, topic: str, hook_description: str, visual_style: str) -> str:
        candidate = (template or "").strip()
        if candidate in self.template_names:
            return candidate
        combined = f"{topic} {hook_description} {visual_style}".lower()
        if any(token in combined for token in ("dark", "proxy", "cyber", "cinematic", "noir")):
            return "dark_cinematic"
        if any(token in combined for token in ("pet", "cat", "кот", "animal")):
            return "funny_pet_contrast"
        if any(token in combined for token in ("cta", "offer", "performance", "закажи", "купи")):
            return "problem_solution_cta"
        if any(token in combined for token in ("fandom", "wizard", "cosplay", "harry", "hogwarts")):
            return "fandom_reveal_parody"
        return "meme_problem_solution"

    def _normalize_aspect(self, aspect: str | None) -> str:
        candidate = (aspect or "").strip()
        if candidate in {"9:16", "16:9", "1:1"}:
            return candidate
        return settings.DEFAULT_ASPECT

    def _scene_count_for_duration(self, duration_sec: int) -> int:
        if duration_sec <= 6:
            return 2
        if duration_sec <= 10:
            return 3
        if duration_sec <= 16:
            return 4
        return 5

    def _fit_lines(self, lines: list[str], scene_count: int) -> list[str]:
        items = [item.strip() for item in lines if item and item.strip()]
        if len(items) >= scene_count:
            return items[:scene_count]
        return items

    def _merge_lines(self, preferred: list[str], defaults: list[str], scene_count: int) -> list[str]:
        merged = self._fit_lines(preferred, scene_count)
        fallback = self._fit_lines(defaults, scene_count)
        if len(merged) >= scene_count:
            return merged[:scene_count]
        for item in fallback:
            if len(merged) >= scene_count:
                break
            merged.append(item)
        return merged[:scene_count]

    def _split_duration(self, total_duration: float, scene_count: int) -> list[float]:
        if scene_count <= 1:
            return [round(total_duration, 2)]
        base = round(total_duration / scene_count, 2)
        durations = [base for _ in range(scene_count)]
        durations[-1] = round(total_duration - sum(durations[:-1]), 2)
        return durations

    def _mode_for_source_mode(self, source_mode: str) -> GenerationMode:
        if source_mode == "reference_video":
            return GenerationMode.REFERENCE_BASED
        return GenerationMode.TEMPLATE_ONLY

    def _clamp_int(self, value: int, lower: int, upper: int, fallback: int) -> int:
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            return fallback
        return max(lower, min(upper, candidate))

    def _dedupe_notes(self, notes: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for note in notes:
            candidate = note.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            unique.append(candidate)
        return unique

    def _fallback_reply(self, source_mode: str, topic: str, has_logo: bool, language: str) -> str:
        if language == "ru":
            if source_mode == "reference_video":
                return f"Разобрал запрос. Возьму референс-видео как основу движения и соберу ролик вокруг темы: {topic}."
            if source_mode == "image_sequence":
                return f"Разобрал запрос. Референс-видео нет, поэтому соберу ролик из загруженных картинок вокруг темы: {topic}."
            logo_note = " Логотип добавлю как brand overlay." if has_logo else ""
            return f"Разобрал запрос. Визуальных референсов нет, поэтому запущу text-only генерацию вокруг темы: {topic}.{logo_note}"
        if source_mode == "reference_video":
            return f"I parsed the prompt and will use the reference video as the motion base for: {topic}."
        if source_mode == "image_sequence":
            return f"I parsed the prompt and will build the video from the uploaded images for: {topic}."
        return f"I parsed the prompt and will run a text-only generation flow for: {topic}."

    def unique_project_name(self, base_name: str, suffix_seed: str | None = None) -> str:
        normalized = safe_slug(base_name)
        if suffix_seed:
            return f"{base_name} {suffix_seed}"[:100]
        return (base_name or normalized or "Prompt Studio")[:100]
