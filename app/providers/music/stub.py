from pathlib import Path

from app.core.config import settings
from app.utils.media import generate_tone_audio, loop_audio_to_duration


class FallbackMusicProvider:
    def get_track(self, mood: str, duration_sec: int, output_path: Path, config: dict[str, object]) -> Path:
        library_dir = Path(config.get("library_dir") or settings.assets_root / "music_library")
        if library_dir.exists():
            candidates = sorted(
                path
                for path in library_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac"}
            )
            if candidates:
                return loop_audio_to_duration(candidates[0], output_path, duration_sec)

        frequency = 140 + (abs(hash(mood)) % 160)
        return generate_tone_audio(output_path, duration_sec, frequency=frequency, volume=0.06)
