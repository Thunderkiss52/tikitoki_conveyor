from __future__ import annotations

from pathlib import Path

from app.db.models import Job, Project
from app.models.pipeline import MediaArtifact, ScriptPackage, ShotSpec
from app.utils.media import concat_audio, concat_video, loop_audio_to_duration, mix_audio, mux_video_with_audio
from app.utils.storage import resolve_local_path, to_workspace_path, write_text


class ComposerService:
    def run(
        self,
        project: Project,
        job: Job,
        shots: list[ShotSpec],
        script: ScriptPackage,
        video_assets: list[MediaArtifact],
        voice_assets: list[MediaArtifact],
        music_asset: MediaArtifact | None,
        job_dirs: dict[str, Path],
    ) -> dict[str, str | None]:
        clip_paths = [resolve_local_path(asset.path) for asset in video_assets]
        if not clip_paths:
            raise RuntimeError("No video clips generated for composition.")

        base_video_path = job_dirs["output"] / "base_video.mp4"
        concat_video(clip_paths, base_video_path)

        combined_voice_path: Path | None = None
        if voice_assets:
            combined_voice_path = job_dirs["output"] / "voiceover.wav"
            concat_audio([resolve_local_path(asset.path) for asset in voice_assets], combined_voice_path)

        prepared_music_path: Path | None = None
        if music_asset:
            prepared_music_path = job_dirs["output"] / "music_bed.wav"
            loop_audio_to_duration(resolve_local_path(music_asset.path), prepared_music_path, job.duration_sec)

        mixed_audio_path: Path | None = None
        if combined_voice_path or prepared_music_path:
            mixed_audio_path = job_dirs["output"] / "mixed_audio.wav"
            mixed_audio_path = mix_audio(combined_voice_path, prepared_music_path, mixed_audio_path)

        subtitles_path = job_dirs["subtitles"] / "subtitles.srt"
        self._write_subtitles(
            subtitles_path,
            shots,
            script.voiceover if script.voiceover else script.overlays,
        )

        logo_path = None
        if job.config_json.get("brand_overlay", True) and project.config_json.get("logo_path"):
            candidate = resolve_local_path(project.config_json["logo_path"])
            if candidate.exists():
                logo_path = candidate

        composed_path = job_dirs["output"] / "composed.mp4"
        mux_video_with_audio(
            video_path=base_video_path,
            output_path=composed_path,
            audio_path=mixed_audio_path,
            subtitles_path=subtitles_path if job.config_json.get("subtitles", True) else None,
            logo_path=logo_path,
        )

        return {
            "composed_video": to_workspace_path(composed_path),
            "subtitles": to_workspace_path(subtitles_path),
            "voiceover_track": to_workspace_path(combined_voice_path) if combined_voice_path else None,
            "music_track": to_workspace_path(prepared_music_path) if prepared_music_path else None,
        }

    def _write_subtitles(self, output_path: Path, shots: list[ShotSpec], lines: list[str]) -> None:
        blocks: list[str] = []
        current_time = 0.0
        for index, shot in enumerate(shots, start=1):
            line = lines[index - 1] if index - 1 < len(lines) else shot.overlay
            end_time = current_time + shot.duration_sec
            blocks.append(
                "\n".join(
                    [
                        str(index),
                        f"{self._format_time(current_time)} --> {self._format_time(end_time)}",
                        line,
                    ]
                )
            )
            current_time = end_time

        write_text(output_path, "\n\n".join(blocks) + "\n")

    def _format_time(self, seconds: float) -> str:
        total_milliseconds = int(round(seconds * 1000))
        hours, remainder = divmod(total_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, milliseconds = divmod(remainder, 1_000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
