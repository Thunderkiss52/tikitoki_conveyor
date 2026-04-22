from pathlib import Path

from app.db.models import Job, Project
from app.models.pipeline import MediaArtifact, TrendAnalysis
from app.providers.music.base import MusicProvider
from app.utils.storage import to_workspace_path


class MusicGenerationService:
    def __init__(self, provider: MusicProvider) -> None:
        self.provider = provider

    def run(self, project: Project, job: Job, analysis: TrendAnalysis, job_dirs: dict[str, Path]) -> MediaArtifact:
        output_path = job_dirs["music"] / "music.wav"
        self.provider.get_track(
            mood=analysis.mood,
            duration_sec=job.duration_sec,
            output_path=output_path,
            config={
                **project.config_json,
                **job.config_json,
            },
        )
        return MediaArtifact(
            path=to_workspace_path(output_path),
            metadata={"mood": analysis.mood, "provider": job.config_json.get("music_provider")},
        )
