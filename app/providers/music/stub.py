from pathlib import Path

from app.core.config import settings
from app.utils.media import generate_procedural_music, loop_audio_to_duration


class FallbackMusicProvider:
    def get_track(self, mood: str, duration_sec: int, output_path: Path, config: dict[str, object]) -> Path:
        library_dir = Path(config.get("library_dir") or settings.assets_root / "music_library")
        library_dir.mkdir(parents=True, exist_ok=True)
        if library_dir.exists():
            candidates = sorted(
                path
                for path in library_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac"}
            )
            if candidates:
                best_match = self._pick_candidate(candidates, mood)
                return loop_audio_to_duration(best_match, output_path, duration_sec)

        cached_fallback = library_dir / self._fallback_name(mood)
        if not cached_fallback.exists():
            generate_procedural_music(cached_fallback, 8, mood)
        return loop_audio_to_duration(cached_fallback, output_path, duration_sec)

    def _pick_candidate(self, candidates: list[Path], mood: str) -> Path:
        mood_terms = {token for token in mood.lower().replace("-", " ").split() if token}
        scored: list[tuple[int, str, Path]] = []
        for candidate in candidates:
            name_terms = {token for token in candidate.stem.lower().replace("-", " ").replace("_", " ").split() if token}
            score = len(mood_terms & name_terms)
            scored.append((score, candidate.name.lower(), candidate))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]

    def _fallback_name(self, mood: str) -> str:
        normalized = "_".join(token for token in mood.lower().replace("-", " ").split() if token) or "default"
        return f"{normalized}_loop.wav"
