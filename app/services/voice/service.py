from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.db.models import Job, Project
from app.models.pipeline import MediaArtifact, ScriptPackage, ShotSpec
from app.providers.tts.base import TTSProvider
from app.utils.media import fit_audio_to_duration
from app.utils.storage import to_workspace_path, write_text


class VoiceGenerationService:
    def __init__(self, provider: TTSProvider) -> None:
        self.provider = provider

    def run(
        self,
        project: Project,
        job: Job,
        shots: list[ShotSpec],
        script: ScriptPackage,
        job_dirs: dict[str, Path],
    ) -> list[MediaArtifact]:
        if not job.config_json.get("voiceover", True):
            return []

        max_parallel = max(1, int(job.config_json.get("max_parallel_tts", 1)))
        if max_parallel == 1:
            artifacts = [
                self._synthesize_scene(project, job, shot, text, job_dirs)
                for shot, text in zip(shots, script.voiceover, strict=False)
            ]
        else:
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                futures = [
                    executor.submit(self._synthesize_scene, project, job, shot, text, job_dirs)
                    for shot, text in zip(shots, script.voiceover, strict=False)
                ]
                artifacts = [future.result() for future in futures]

        write_text(job_dirs["voice"] / "voiceover.txt", "\n".join(script.voiceover))
        return sorted(artifacts, key=lambda artifact: int(artifact.metadata["order"]))

    def _synthesize_scene(
        self,
        project: Project,
        job: Job,
        shot: ShotSpec,
        text: str,
        job_dirs: dict[str, Path],
    ) -> MediaArtifact:
        raw_output_path = job_dirs["voice"] / f"scene_{shot.order:02d}.raw.wav"
        output_path = job_dirs["voice"] / f"scene_{shot.order:02d}.wav"
        self.provider.synthesize(
            text=text,
            voice_preset=str(project.config_json.get("voice_style", "neutral")),
            output_path=raw_output_path,
            config={
                **job.config_json,
                "language": job.language,
                "duration_sec": shot.duration_sec,
                "shot_order": shot.order,
            },
        )
        fit_audio_to_duration(raw_output_path, output_path, shot.duration_sec)
        raw_output_path.unlink(missing_ok=True)
        return MediaArtifact(
            path=to_workspace_path(output_path),
            metadata={"order": shot.order, "text": text},
        )
