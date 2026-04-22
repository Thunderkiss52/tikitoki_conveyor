from pathlib import Path
from typing import Protocol


class TTSProvider(Protocol):
    def synthesize(self, text: str, voice_preset: str, output_path: Path, config: dict[str, object]) -> Path:
        ...
