from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.utils.storage import resolve_local_path, to_workspace_path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional during local installs
    Image = None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_EXTENSIONS = {".wav", ".mp3"}
DISCOVERABLE_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | {".json"}
MUTABLE_ASSET_ROOTS = (
    settings.assets_root / "logos",
    settings.assets_root / "uploads",
    settings.assets_root / "music_library",
)
LOGO_MODE_CHOICES = ("auto_emblem", "keep_full_image")


def detect_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return "data"


def asset_static_url(path: Path) -> str | None:
    workspace_path = to_workspace_path(path).replace("\\", "/")
    if workspace_path.startswith("storage/"):
        return f"/{workspace_path}"
    return None


def is_mutable_asset(path: Path) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in MUTABLE_ASSET_ROOTS)


def delete_managed_asset(path_value: str) -> Path:
    target_path = resolve_local_path(path_value)
    if not target_path.exists() or not target_path.is_file():
        raise FileNotFoundError(f"Asset not found: {target_path}")
    if not is_mutable_asset(target_path):
        raise PermissionError(f"Asset is not managed by Asset Library: {target_path}")
    target_path.unlink()
    return target_path


def normalize_logo_upload(content: bytes, mode: str) -> tuple[bytes, str | None, dict[str, Any]]:
    if mode not in LOGO_MODE_CHOICES:
        raise ValueError(f"Unsupported logo mode: {mode}")

    metadata: dict[str, Any] = {"logo_mode": mode, "auto_emblem_applied": False}
    if mode != "auto_emblem" or Image is None:
        if Image is None and mode == "auto_emblem":
            metadata["warning"] = "Pillow is not installed; keeping the original image"
        return content, None, metadata

    try:
        source = Image.open(BytesIO(content)).convert("RGBA")
    except Exception as exc:  # pragma: no cover - depends on image decoder runtime
        raise ValueError("Uploaded logo is not a readable image") from exc
    processed, crop_meta = _extract_emblem(source)
    buffer = BytesIO()
    processed.save(buffer, format="PNG")
    metadata.update(crop_meta)
    metadata["auto_emblem_applied"] = True
    return buffer.getvalue(), ".png", metadata


def _extract_emblem(source: Image.Image) -> tuple[Image.Image, dict[str, Any]]:
    alpha_bbox = source.getchannel("A").getbbox()
    if alpha_bbox is not None and alpha_bbox != (0, 0, source.width, source.height):
        cropped = source.crop(_expand_bbox(alpha_bbox, source.size))
        return cropped, {"bbox": list(alpha_bbox), "crop_source": "alpha"}

    background = _estimate_background_rgba(source)
    tolerance = 56
    pixels = source.load()
    foreground_bbox: tuple[int, int, int, int] | None = None

    for y in range(source.height):
        for x in range(source.width):
            pixel = pixels[x, y]
            if _is_foreground(pixel, background, tolerance):
                if foreground_bbox is None:
                    foreground_bbox = (x, y, x + 1, y + 1)
                else:
                    left, top, right, bottom = foreground_bbox
                    foreground_bbox = (
                        min(left, x),
                        min(top, y),
                        max(right, x + 1),
                        max(bottom, y + 1),
                    )

    if foreground_bbox is None:
        return source, {"bbox": [0, 0, source.width, source.height], "crop_source": "fallback"}

    expanded_bbox = _expand_bbox(foreground_bbox, source.size)
    cropped = source.crop(expanded_bbox)
    cropped_pixels = cropped.load()
    for y in range(cropped.height):
        for x in range(cropped.width):
            red, green, blue, alpha = cropped_pixels[x, y]
            if alpha <= 10:
                continue
            if not _is_foreground((red, green, blue, alpha), background, tolerance):
                cropped_pixels[x, y] = (red, green, blue, 0)

    return cropped, {"bbox": list(expanded_bbox), "crop_source": "background"}


def _estimate_background_rgba(source: Image.Image) -> tuple[int, int, int, int]:
    sample_radius = max(3, min(source.width, source.height) // 14)
    samples: list[tuple[int, int, int, int]] = []
    corners = (
        (0, 0),
        (max(source.width - sample_radius, 0), 0),
        (0, max(source.height - sample_radius, 0)),
        (max(source.width - sample_radius, 0), max(source.height - sample_radius, 0)),
    )
    pixels = source.load()
    for origin_x, origin_y in corners:
        for y in range(origin_y, min(origin_y + sample_radius, source.height)):
            for x in range(origin_x, min(origin_x + sample_radius, source.width)):
                samples.append(pixels[x, y])

    if not samples:
        return (255, 255, 255, 255)

    red = round(sum(sample[0] for sample in samples) / len(samples))
    green = round(sum(sample[1] for sample in samples) / len(samples))
    blue = round(sum(sample[2] for sample in samples) / len(samples))
    alpha = round(sum(sample[3] for sample in samples) / len(samples))
    return (red, green, blue, alpha)


def _is_foreground(pixel: tuple[int, int, int, int], background: tuple[int, int, int, int], tolerance: int) -> bool:
    red, green, blue, alpha = pixel
    if alpha <= 10:
        return False
    diff = abs(red - background[0]) + abs(green - background[1]) + abs(blue - background[2])
    return diff > tolerance


def _expand_bbox(bbox: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    padding_x = max(6, round(width * 0.08))
    padding_y = max(6, round(height * 0.08))
    max_width, max_height = size
    return (
        max(0, left - padding_x),
        max(0, top - padding_y),
        min(max_width, right + padding_x),
        min(max_height, bottom + padding_y),
    )
