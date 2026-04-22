from pathlib import Path

from app.models.pipeline import ShotSpec
from app.utils.media import generate_color_clip


class StubVideoProvider:
    def generate(self, shot_spec: ShotSpec, output_path: Path, config: dict[str, object]) -> Path:
        width = int(config.get("width", 1080))
        height = int(config.get("height", 1920))
        seed = f"{shot_spec.prompt}:{shot_spec.overlay}:{shot_spec.type}"
        return generate_color_clip(output_path, shot_spec.duration_sec, width, height, seed)
