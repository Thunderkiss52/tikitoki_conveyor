from pathlib import Path

from app.db.models import Job, Project
from app.models.pipeline import ScriptPackage, ShotSpec, TrendAnalysis
from app.utils.storage import write_json


class ShotPlannerService:
    def run(
        self,
        project: Project,
        job: Job,
        analysis: TrendAnalysis,
        script: ScriptPackage,
        output_path: Path,
    ) -> list[ShotSpec]:
        shot_overrides = job.config_json.get("shot_overrides")
        if shot_overrides:
            shots = self._build_overridden_shots(job, script, shot_overrides)
            write_json(output_path, {"shots": [shot.model_dump() for shot in shots]})
            return shots

        shot_count = max(len(script.voiceover), len(analysis.beats), job.scene_count)
        durations = self._split_duration(job.duration_sec, shot_count)
        shots: list[ShotSpec] = []

        for index in range(shot_count):
            beat = analysis.beats[index] if index < len(analysis.beats) else "cta"
            overlay = script.overlays[index] if index < len(script.overlays) else project.name
            prompt = self._build_prompt(
                beat=beat,
                topic=job.topic,
                project_name=project.name,
                mood=analysis.mood,
                camera_style=analysis.camera_style,
            )
            shots.append(
                ShotSpec(
                    order=index + 1,
                    duration_sec=durations[index],
                    type=beat,
                    prompt=prompt,
                    camera="close-up" if index == 0 else "medium shot",
                    motion="slight handheld" if analysis.pace == "fast" else "slow dolly",
                    overlay=overlay,
                    transition="cut" if analysis.pace == "fast" else "fade",
                    metadata={"template": script.template},
                )
            )

        write_json(output_path, {"shots": [shot.model_dump() for shot in shots]})
        return shots

    def _build_overridden_shots(
        self,
        job: Job,
        script: ScriptPackage,
        shot_overrides: list[dict],
    ) -> list[ShotSpec]:
        durations = self._split_duration(job.duration_sec, len(shot_overrides))
        shots: list[ShotSpec] = []

        for index, override in enumerate(shot_overrides, start=1):
            prompt = str(override["prompt"])
            overlay = str(
                override.get("overlay")
                or (script.overlays[index - 1] if index - 1 < len(script.overlays) else "")
            )
            metadata = {
                "negative_prompt": override.get("negative_prompt", ""),
                "provider_settings": override.get("provider_settings", {}),
            }
            shots.append(
                ShotSpec(
                    order=index,
                    duration_sec=float(override.get("duration_sec") or durations[index - 1]),
                    type=str(override.get("type", f"scene_{index}")),
                    prompt=prompt,
                    camera=str(override.get("camera", "medium shot")),
                    motion=str(override.get("motion", "slight handheld")),
                    overlay=overlay,
                    transition=str(override.get("transition", "cut")),
                    metadata=metadata,
                )
            )

        return shots

    def _split_duration(self, total_duration: int, shot_count: int) -> list[float]:
        base_duration = round(total_duration / shot_count, 2)
        durations = [base_duration for _ in range(shot_count)]
        durations[-1] = round(total_duration - sum(durations[:-1]), 2)
        return durations

    def _build_prompt(
        self,
        beat: str,
        topic: str,
        project_name: str,
        mood: str,
        camera_style: str,
    ) -> str:
        prompt_map = {
            "problem": f"frustrated person hits the same obstacle around {topic}, {mood}, vertical video",
            "human_fails": f"human fails in a funny way around {topic}, meme timing, vertical video",
            "hook_closeup": f"tense close-up around {topic}, {mood}, dramatic lighting",
            "contrast": f"clear contrast appears, {project_name} theme, {camera_style}",
            "pet_succeeds": f"small smart animal succeeds easily where human fails, humorous, vertical video",
            "reveal": f"brand reveal for {project_name}, sleek dark cinematic motion",
            "solution": f"simple smooth solution for {topic}, product clarity, {project_name}",
            "brand_line": f"strong brand frame with {project_name} identity and clean CTA space",
            "brand_punchline": f"comedic payoff frame with {project_name} identity and meme rhythm",
            "cta": f"final direct CTA card for {project_name}, clean readable space",
        }
        return prompt_map.get(beat, f"short branded scene about {topic} for {project_name}")
