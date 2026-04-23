from __future__ import annotations

from pathlib import Path

from app.db.models import Job, Project, TrendSource
from app.models.pipeline import IngestResult, TrendAnalysis
from app.utils.storage import write_json


class TrendAnalyzerService:
    def run(
        self,
        project: Project,
        job: Job,
        trend_source: TrendSource,
        ingest_result: IngestResult,
        output_path: Path,
    ) -> TrendAnalysis:
        override = job.config_json.get("trend_analysis_override")
        if override:
            analysis = TrendAnalysis.model_validate(override)
            write_json(output_path, analysis.model_dump())
            return analysis

        mood = self._infer_mood(project, job, trend_source)
        beats = self._infer_beats(job.scene_count, mood)
        duration = ingest_result.source_meta.get("duration_sec") or job.duration_sec
        analysis = TrendAnalysis(
            hook=trend_source.hook_description or f"{beats[0]} in first 1.5 sec",
            beats=beats,
            estimated_scene_count=job.scene_count,
            pace="fast" if float(duration) <= 10 else "medium",
            camera_style="static + close-up" if mood != "dark cyber tension" else "dramatic push-in",
            mood=mood,
            references={
                "frame_count": len(ingest_result.frames),
                "duration_sec": duration,
                "source_meta": ingest_result.source_meta,
            },
        )
        write_json(output_path, analysis.model_dump())
        return analysis

    def _infer_mood(self, project: Project, job: Job, trend_source: TrendSource) -> str:
        combined_text = " ".join(
            filter(
                None,
                [
                    job.topic,
                    trend_source.hook_description or "",
                    str(project.config_json.get("music_style", "")),
                ],
            )
        ).lower()
        if any(keyword in combined_text for keyword in ("harry", "potter", "fandom", "cosplay", "wizard", "hogwarts")):
            return "fandom parody reveal"
        if any(keyword in combined_text for keyword in ("dark", "proxy", "cyber", "telegram")):
            return "dark cyber tension"
        if any(keyword in combined_text for keyword in ("cat", "кот", "pet", "animal")):
            return "funny contrast"
        return "comic contrast"

    def _infer_beats(self, scene_count: int, mood: str) -> list[str]:
        if mood == "fandom parody reveal":
            return ["hook_closeup", "contrast", "contrast", "reveal", "brand_punchline"][:scene_count]
        if scene_count >= 4:
            return ["problem", "contrast", "solution", "cta"][:scene_count]
        if mood == "dark cyber tension":
            return ["hook_closeup", "reveal", "brand_line"][:scene_count]
        if mood == "funny contrast":
            return ["human_fails", "pet_succeeds", "brand_punchline"][:scene_count]
        return ["problem", "contrast", "solution"][:scene_count]
