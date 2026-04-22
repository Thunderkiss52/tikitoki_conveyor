from pathlib import Path

from app.utils.media import generate_silent_audio


class SilentTTSProvider:
    def synthesize(self, text: str, voice_preset: str, output_path: Path, config: dict[str, object]) -> Path:
        requested_duration = config.get("duration_sec")
        duration = float(requested_duration) if requested_duration else max(1.2, len(text.split()) * 0.55)
        return generate_silent_audio(output_path, duration)
