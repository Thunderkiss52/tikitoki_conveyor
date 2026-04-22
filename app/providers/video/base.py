from pathlib import Path
from typing import Protocol

from app.models.pipeline import ShotSpec


class VideoProvider(Protocol):
    def generate(self, shot_spec: ShotSpec, output_path: Path, config: dict[str, object]) -> Path:
        ...
