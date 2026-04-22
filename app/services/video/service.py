from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.db.models import Job, Project
from app.models.pipeline import MediaArtifact, ShotSpec
from app.providers.video.base import VideoProvider
from app.utils.storage import to_workspace_path


class VideoGenerationService:
    def __init__(self, provider: VideoProvider) -> None:
        self.provider = provider

    def run(self, project: Project, job: Job, shots: list[ShotSpec], job_dirs: dict[str, Path]) -> list[MediaArtifact]:
        width, height = self._target_resolution(project, job)
        max_parallel = max(1, int(job.config_json.get("max_parallel_video_shots", 1)))
        build_payload = lambda shot: {
            "width": width,
            "height": height,
            "project_name": project.name,
            "brand_image_path": project.config_json.get("logo_path"),
            "negative_prompt": shot.metadata.get("negative_prompt", ""),
            "provider_settings": shot.metadata.get("provider_settings", {}),
        }

        if max_parallel == 1:
            return [self._generate_shot(shot, job_dirs, build_payload(shot)) for shot in shots]

        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            futures = [
                executor.submit(self._generate_shot, shot, job_dirs, build_payload(shot))
                for shot in shots
            ]
            artifacts = [future.result() for future in futures]

        return sorted(artifacts, key=lambda artifact: int(artifact.metadata["order"]))

    def _target_resolution(self, project: Project, job: Job) -> tuple[int, int]:
        aspect = job.config_json.get("aspect") or project.config_json.get("default_aspect", "9:16")
        if aspect == "16:9":
            return 1920, 1080
        if aspect == "1:1":
            return 1080, 1080
        return 1080, 1920

    def _generate_shot(
        self,
        shot: ShotSpec,
        job_dirs: dict[str, Path],
        provider_payload: dict[str, object],
    ) -> MediaArtifact:
        output_path = job_dirs["shots"] / f"clip_{shot.order:02d}.mp4"
        self.provider.generate(shot, output_path, provider_payload)
        return MediaArtifact(
            path=to_workspace_path(output_path),
            metadata={"order": shot.order, "shot_type": shot.type},
        )
