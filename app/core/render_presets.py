from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_GENERATION_MODE = "video_to_video"
DEFAULT_QUALITY_PRESET = "high"

GENERATION_MODE_ALIASES = {
    "text": "text_to_video",
    "text2video": "text_to_video",
    "text_to_video": "text_to_video",
    "image": "image_to_video",
    "image2video": "image_to_video",
    "image_to_video": "image_to_video",
    "video": "video_to_video",
    "video2video": "video_to_video",
    "video_to_video": "video_to_video",
}

QUALITY_PRESET_ALIASES = {
    "fast": "draft",
    "draft": "draft",
    "standard": "standard",
    "high": "high",
    "ultra": "ultra",
    "max": "ultra",
}

COMFYUI_WORKFLOWS = {
    "text_to_video": "workflows/comfyui_ui/01_text_to_video_basic.json",
    "image_to_video": "workflows/comfyui_ui/02_image_to_video_basic.json",
    "video_to_video": "workflows/comfyui_ui/03_video_to_video_soft_remake.json",
}

MODE_DEFAULTS: dict[str, dict[str, Any]] = {
    "text_to_video": {
        "denoise": 1.0,
    },
    "image_to_video": {
        "denoise": 0.55,
    },
    "video_to_video": {
        "denoise": 0.45,
    },
}

QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "draft": {
        "resolution": "432x768",
        "frames": 8,
        "steps": 8,
        "cfg": 6.5,
        "fps": 8.0,
    },
    "standard": {
        "resolution": "512x912",
        "frames": 12,
        "steps": 16,
        "cfg": 7.0,
        "fps": 8.0,
    },
    "high": {
        "resolution": "576x1024",
        "frames": 16,
        "steps": 24,
        "cfg": 7.5,
        "fps": 8.0,
    },
    "ultra": {
        "resolution": "576x1024",
        "frames": 20,
        "steps": 28,
        "cfg": 7.5,
        "fps": 8.0,
    },
}


GENERATION_MODE_CHOICES = tuple(COMFYUI_WORKFLOWS)
QUALITY_PRESET_CHOICES = tuple(QUALITY_PRESETS)


def normalize_generation_mode(value: str | None) -> str:
    raw_value = (value or DEFAULT_GENERATION_MODE).strip().lower().replace("-", "_")
    resolved = GENERATION_MODE_ALIASES.get(raw_value)
    if resolved is None:
        supported = ", ".join(sorted(GENERATION_MODE_CHOICES))
        raise ValueError(f"Unsupported generation mode: {value}. Expected one of: {supported}")
    return resolved


def normalize_quality_preset(value: str | None) -> str:
    raw_value = (value or DEFAULT_QUALITY_PRESET).strip().lower()
    resolved = QUALITY_PRESET_ALIASES.get(raw_value)
    if resolved is None:
        supported = ", ".join(sorted(QUALITY_PRESET_CHOICES))
        raise ValueError(f"Unsupported quality preset: {value}. Expected one of: {supported}")
    return resolved


def default_workflow_path(mode: str | None = None) -> Path:
    resolved_mode = normalize_generation_mode(mode)
    path = Path(COMFYUI_WORKFLOWS[resolved_mode])
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def infer_generation_mode_from_workflow_path(value: str | Path | None) -> str | None:
    if not value:
        return None
    path = str(value).lower()
    if "01_text" in path or "text_to_video" in path:
        return "text_to_video"
    if "02_image" in path or "image_to_video" in path:
        return "image_to_video"
    if "03_video" in path or "video_to_video" in path:
        return "video_to_video"
    return None


def build_comfyui_provider_settings(
    mode: str | None = None,
    quality: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overrides = dict(overrides or {})
    resolved_mode = normalize_generation_mode(
        overrides.get("generation_mode")
        or overrides.get("mode")
        or infer_generation_mode_from_workflow_path(overrides.get("workflow_path"))
        or mode
    )
    resolved_quality = normalize_quality_preset(overrides.get("quality_preset") or quality)

    settings: dict[str, Any] = {}
    settings.update(QUALITY_PRESETS[resolved_quality])
    settings.update(MODE_DEFAULTS[resolved_mode])
    settings["generation_mode"] = resolved_mode
    settings["quality_preset"] = resolved_quality
    settings["workflow_path"] = str(default_workflow_path(resolved_mode))

    for key, value in overrides.items():
        if value is None:
            continue
        settings[key] = value

    return settings
