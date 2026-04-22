from pathlib import Path

from app.db.models import Job, Project
from app.models.pipeline import ScriptPackage, TrendAnalysis
from app.providers.llm.base import ScriptProvider
from app.utils.storage import write_json


class ScriptGeneratorService:
    def __init__(self, provider: ScriptProvider) -> None:
        self.provider = provider

    def run(self, project: Project, job: Job, analysis: TrendAnalysis, output_path: Path) -> ScriptPackage:
        script = self.provider.generate_script(
            {
                "project_name": project.name,
                "project_config": project.config_json,
                "topic": job.topic,
                "analysis": analysis.model_dump(),
                "scene_count": job.scene_count,
                "template": job.config_json.get("template"),
                "cta": job.config_json.get("cta"),
                "language": job.language,
            }
        )
        script = self._apply_overrides(job, script)
        write_json(output_path, script.model_dump())
        return script

    def _apply_overrides(self, job: Job, script: ScriptPackage) -> ScriptPackage:
        config = job.config_json
        title = config.get("title_override") or config.get("title") or script.title
        voiceover = config.get("voiceover_override") or config.get("voiceover_lines") or script.voiceover
        overlays = config.get("overlay_override") or config.get("overlays_override") or config.get("overlay_lines") or script.overlays
        cta = config.get("cta") or script.cta

        return ScriptPackage(
            title=title,
            template=config.get("template") or script.template,
            voiceover=list(voiceover),
            overlays=list(overlays),
            cta=str(cta),
        )
