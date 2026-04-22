from __future__ import annotations

from pathlib import Path

from app.db.models import Job, TrendSource
from app.models.pipeline import IngestResult
from app.utils.media import extract_frames, ffprobe_media
from app.utils.storage import copy_file, resolve_local_path, to_workspace_path, write_json


class IngestService:
    def run(self, trend_source: TrendSource, job: Job, job_dirs: dict[str, Path]) -> IngestResult:
        source_meta = {
            "duration_sec": job.duration_sec,
            "resolution": None,
            "fps": None,
            "synthetic_source": trend_source.type.value != "video",
        }
        copied_source_path = ""
        extracted_frames: list[str] = []

        if trend_source.type.value == "video":
            source_path = resolve_local_path(trend_source.source_path)
            if not source_path.exists():
                raise FileNotFoundError(f"Trend source file not found: {source_path}")

            target_path = job_dirs["source"] / f"source{source_path.suffix or '.mp4'}"
            copy_file(source_path, target_path)
            copied_source_path = to_workspace_path(target_path)

            try:
                source_meta = {**source_meta, **ffprobe_media(target_path)}
            except Exception as exc:
                source_meta["probe_error"] = str(exc)

            try:
                extracted_frames = [
                    to_workspace_path(frame_path)
                    for frame_path in extract_frames(target_path, job_dirs["frames"], max_frames=min(job.scene_count + 1, 6))
                ]
            except Exception as exc:
                source_meta["frame_extract_error"] = str(exc)

        write_json(job_dirs["data"] / "source_meta.json", source_meta)

        return IngestResult(
            source_path=copied_source_path,
            frames=extracted_frames,
            source_meta=source_meta,
        )
