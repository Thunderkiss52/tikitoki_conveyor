from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.pipeline import ShotSpec
from app.utils.media import (
    render_brand_reveal_clip,
    render_hodor_action_clip,
    render_phone_ui_clip,
    render_reference_video_clip,
)
from app.utils.storage import resolve_local_path


class ReferenceVideoProvider:
    def generate(self, shot_spec: ShotSpec, output_path: Path, config: dict[str, object]) -> Path:
        provider_settings = dict(config.get("provider_settings") or {})
        width, height = self._resolve_resolution(config, provider_settings)
        source_kind = str(provider_settings.get("source_kind") or provider_settings.get("source_type") or "video").lower()
        fps = self._coerce_float(provider_settings.get("fps"), 30.0)

        if source_kind in {"ui_problem", "phone_problem"}:
            return render_phone_ui_clip(
                output_path=output_path,
                duration_sec=shot_spec.duration_sec,
                width=width,
                height=height,
                state="problem",
                fps=fps,
            )

        if source_kind in {"ui_block", "block_barrier", "firewall"}:
            return render_phone_ui_clip(
                output_path=output_path,
                duration_sec=shot_spec.duration_sec,
                width=width,
                height=height,
                state="blocked",
                fps=fps,
            )

        if source_kind in {"ui_clear", "access_restored", "result_open"}:
            return render_phone_ui_clip(
                output_path=output_path,
                duration_sec=shot_spec.duration_sec,
                width=width,
                height=height,
                state="clear",
                fps=fps,
            )

        if source_kind in {"hodor_spin", "hodor_impact", "impact"}:
            image_path = self._resolve_source_path(
                provider_settings.get("source_path")
                or provider_settings.get("reference_image_path")
                or provider_settings.get("brand_image_path")
                or config.get("brand_image_path")
            )
            return render_hodor_action_clip(
                input_path=image_path,
                output_path=output_path,
                duration_sec=shot_spec.duration_sec,
                width=width,
                height=height,
                action="impact" if source_kind in {"hodor_impact", "impact"} else "spin",
                fps=fps,
            )

        if source_kind in {"image", "brand", "image_to_video"}:
            image_path = self._resolve_source_path(
                provider_settings.get("source_path")
                or provider_settings.get("reference_image_path")
                or provider_settings.get("brand_image_path")
                or config.get("brand_image_path")
            )
            return render_brand_reveal_clip(
                input_path=image_path,
                output_path=output_path,
                duration_sec=shot_spec.duration_sec,
                width=width,
                height=height,
                fps=fps,
                fade_in_sec=self._coerce_float(provider_settings.get("fade_in_sec"), 0.35),
                background_blur=self._coerce_int(provider_settings.get("background_blur"), 30),
                background_brightness=self._coerce_float(provider_settings.get("background_brightness"), -0.05),
                background_saturation=self._coerce_float(provider_settings.get("background_saturation"), 0.82),
                image_scale=self._coerce_float(provider_settings.get("image_scale"), 0.72),
                zoom_end=self._coerce_float(provider_settings.get("zoom_end"), 1.08),
            )

        if source_kind in {"hodor_final", "final_neon"}:
            image_path = self._resolve_source_path(
                provider_settings.get("source_path")
                or provider_settings.get("reference_image_path")
                or provider_settings.get("brand_image_path")
                or config.get("brand_image_path")
            )
            return render_brand_reveal_clip(
                input_path=image_path,
                output_path=output_path,
                duration_sec=shot_spec.duration_sec,
                width=width,
                height=height,
                fps=fps,
                fade_in_sec=self._coerce_float(provider_settings.get("fade_in_sec"), 0.18),
                background_blur=self._coerce_int(provider_settings.get("background_blur"), 34),
                background_brightness=self._coerce_float(provider_settings.get("background_brightness"), -0.08),
                background_saturation=self._coerce_float(provider_settings.get("background_saturation"), 0.74),
                image_scale=self._coerce_float(provider_settings.get("image_scale"), 0.62),
                zoom_end=self._coerce_float(provider_settings.get("zoom_end"), 1.10),
            )

        video_path = self._resolve_source_path(
            provider_settings.get("source_path")
            or provider_settings.get("reference_video_path")
            or provider_settings.get("trend_video_path")
        )
        speed = max(self._coerce_float(provider_settings.get("speed"), 1.0), 0.1)
        source_duration = self._coerce_float(
            provider_settings.get("source_duration_sec"),
            shot_spec.duration_sec * speed,
        )
        return render_reference_video_clip(
            input_path=video_path,
            output_path=output_path,
            start_sec=self._coerce_float(provider_settings.get("source_start_sec"), 0.0),
            duration_sec=source_duration,
            output_duration_sec=shot_spec.duration_sec,
            width=width,
            height=height,
            speed=speed,
            punch_in=self._coerce_float(provider_settings.get("punch_in"), 1.04),
            brightness=self._coerce_float(provider_settings.get("brightness"), 0.0),
            contrast=self._coerce_float(provider_settings.get("contrast"), 1.0),
            saturation=self._coerce_float(provider_settings.get("saturation"), 1.0),
            sharpen=self._coerce_float(provider_settings.get("sharpen"), 0.0),
            fps=fps,
            fade_in_sec=self._coerce_float(provider_settings.get("fade_in_sec"), 0.0),
            fade_out_sec=self._coerce_float(provider_settings.get("fade_out_sec"), 0.0),
        )

    def _resolve_resolution(self, config: dict[str, Any], provider_settings: dict[str, Any]) -> tuple[int, int]:
        raw_resolution = provider_settings.get("resolution")
        if isinstance(raw_resolution, str) and "x" in raw_resolution:
            width, height = raw_resolution.lower().split("x", 1)
            return int(width), int(height)
        return int(config.get("width", 1080)), int(config.get("height", 1920))

    def _resolve_source_path(self, raw_value: object) -> Path:
        if not raw_value:
            raise ValueError("Reference provider is missing source_path/reference path.")
        path = resolve_local_path(str(raw_value))
        if not path.exists():
            raise FileNotFoundError(f"Reference asset not found: {path}")
        return path

    def _coerce_float(self, value: object, default: float) -> float:
        if value is None or value == "":
            return default
        return float(value)

    def _coerce_int(self, value: object, default: int) -> int:
        if value is None or value == "":
            return default
        return int(value)
