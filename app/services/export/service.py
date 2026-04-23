from pathlib import Path

from app.db.models import Job, Project
from app.models.pipeline import ExportArtifacts, ScriptPackage, ShotSpec, TrendAnalysis
from app.utils.media import extract_thumbnail, transcode_for_platform
from app.utils.storage import resolve_local_path, to_workspace_path, write_json


class ExporterService:
    def run(
        self,
        project: Project,
        job: Job,
        analysis: TrendAnalysis,
        script: ScriptPackage,
        shots: list[ShotSpec],
        composition: dict[str, str | None],
        job_dirs: dict[str, Path],
    ) -> ExportArtifacts:
        width, height = self._target_resolution(project, job)
        composed_video_path = resolve_local_path(str(composition["composed_video"]))
        final_video_path = job_dirs["output"] / "final.mp4"
        transcode_for_platform(composed_video_path, final_video_path, width, height)

        thumb_path = job_dirs["output"] / "thumb.jpg"
        extract_thumbnail(final_video_path, thumb_path)

        metadata = {
            "job_id": job.id,
            "project_id": job.project_id,
            "trend_source_id": job.trend_source_id,
            "topic": job.topic,
            "status": "done",
            "platform": job.target_platform,
            "duration_sec": job.duration_sec,
            "language": job.language,
            "analysis": analysis.model_dump(),
            "script": script.model_dump(),
            "shots": [shot.model_dump() for shot in shots],
            "outputs": {
                "final_video": to_workspace_path(final_video_path),
                "subtitles": composition["subtitles"],
                "voiceover_track": composition["voiceover_track"],
                "music_track": composition["music_track"],
                "preview_image": to_workspace_path(thumb_path),
            },
            "caption": f"{script.title}. {script.cta}".strip(),
        }
        metadata_path = job_dirs["output"] / "meta.json"
        write_json(metadata_path, metadata)

        return ExportArtifacts(
            final_video=to_workspace_path(final_video_path),
            subtitles=str(composition["subtitles"]),
            voiceover_track=composition["voiceover_track"],
            music_track=composition["music_track"],
            preview_image=to_workspace_path(thumb_path),
            metadata_json=to_workspace_path(metadata_path),
        )

    def _target_resolution(self, project: Project, job: Job) -> tuple[int, int]:
        explicit = str(job.config_json.get("export_resolution") or "").lower()
        if "x" in explicit:
            width, height = explicit.split("x", 1)
            return int(width), int(height)
        aspect = job.config_json.get("aspect") or project.config_json.get("default_aspect", "9:16")
        if aspect == "16:9":
            return 1920, 1080
        if aspect == "1:1":
            return 1080, 1080
        return 1080, 1920
