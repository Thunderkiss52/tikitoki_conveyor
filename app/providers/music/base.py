from pathlib import Path
from typing import Protocol


class MusicProvider(Protocol):
    def get_track(self, mood: str, duration_sec: int, output_path: Path, config: dict[str, object]) -> Path:
        ...
