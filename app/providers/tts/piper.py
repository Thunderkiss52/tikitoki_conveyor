from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.core.config import settings
from app.utils.storage import resolve_local_path


class PiperTTSProvider:
    def synthesize(self, text: str, voice_preset: str, output_path: Path, config: dict[str, object]) -> Path:
        model_path = self._model_path(config, voice_preset)
        binary_path = resolve_local_path(str(config.get("tts_binary_path") or settings.PIPER_BIN))
        if not binary_path.exists():
            raise FileNotFoundError(
                f"Piper binary not found: {binary_path}. Run the Piper install script or configure PIPER_BIN."
            )

        espeak_data = binary_path.parent / "espeak-ng-data"
        if not espeak_data.exists():
            raise FileNotFoundError(f"Piper espeak-ng data directory not found: {espeak_data}")

        length_scale = self._coerce_float(config.get("tts_length_scale"), default=self._default_length_scale(voice_preset))
        noise_scale = self._coerce_float(config.get("tts_noise_scale"), default=0.5)
        noise_w = self._coerce_float(config.get("tts_noise_w"), default=0.7)
        sentence_silence = self._coerce_float(config.get("tts_sentence_silence"), default=0.12)
        speaker = self._coerce_int(config.get("tts_speaker"), default=0)

        command = [
            str(binary_path),
            "--model",
            str(model_path),
            "--output_file",
            str(output_path),
            "--speaker",
            str(speaker),
            "--length_scale",
            f"{length_scale:.3f}",
            "--noise_scale",
            f"{noise_scale:.3f}",
            "--noise_w",
            f"{noise_w:.3f}",
            "--sentence_silence",
            f"{sentence_silence:.3f}",
            "--espeak_data",
            str(espeak_data),
            "--quiet",
        ]

        env = os.environ.copy()
        library_dir = str(binary_path.parent)
        existing_ld_library = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (
            f"{library_dir}:{existing_ld_library}" if existing_ld_library else library_dir
        )

        try:
            subprocess.run(
                command,
                input=text,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(f"Piper synthesis failed: {stderr}") from exc

        if not output_path.exists():
            raise RuntimeError("Piper finished without creating an output WAV file.")
        return output_path

    def _model_path(self, config: dict[str, object], voice_preset: str) -> Path:
        explicit_model_path = config.get("tts_model_path")
        if explicit_model_path:
            path = resolve_local_path(str(explicit_model_path))
        else:
            model_name = str(config.get("tts_model_name") or self._default_model_name(config, voice_preset))
            path = resolve_local_path(Path(settings.PIPER_MODEL_DIR) / model_name)

        if not path.exists():
            raise FileNotFoundError(
                f"Piper voice model not found: {path}. Download the model or configure tts_model_path."
            )
        return path

    def _default_model_name(self, config: dict[str, object], voice_preset: str) -> str:
        requested_language = str(config.get("language") or "").lower()
        if requested_language.startswith("ru") or "male" in voice_preset.lower():
            return Path(settings.PIPER_DEFAULT_MODEL_RU).name
        return Path(settings.PIPER_DEFAULT_MODEL_RU).name

    def _default_length_scale(self, voice_preset: str) -> float:
        preset = voice_preset.lower()
        if "calm" in preset:
            return 1.06
        if "fast" in preset or "energetic" in preset:
            return 0.92
        return 1.0

    def _coerce_float(self, value: object, default: float) -> float:
        if value is None:
            return default
        return float(value)

    def _coerce_int(self, value: object, default: int) -> int:
        if value is None:
            return default
        return int(value)
