from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.enums import AssetType, JobStatus
from app.db.models import Asset, Job, JobShot, LogEntry
from app.db.session import AsyncSessionLocal
from app.models.pipeline import ExportArtifacts, IngestResult, MediaArtifact, ScriptPackage, ShotSpec, TrendAnalysis
from app.providers import get_music_provider, get_script_provider, get_tts_provider, get_video_provider
from app.providers.video import is_synthetic_video_provider
from app.services.analyze.service import TrendAnalyzerService
from app.services.compose.service import ComposerService
from app.services.export.service import ExporterService
from app.services.ingest.service import IngestService
from app.services.jobs.state import PipelineStateManager
from app.services.music.service import MusicGenerationService
from app.services.planning.service import ShotPlannerService
from app.services.scripting.service import ScriptGeneratorService
from app.services.video.service import VideoGenerationService
from app.services.voice.service import VoiceGenerationService
from app.utils.storage import ensure_job_storage, resolve_local_path, to_workspace_path


INGEST_STAGE = JobStatus.INGESTING.value
ANALYZE_STAGE = JobStatus.ANALYZING.value
SCRIPT_STAGE = JobStatus.SCRIPTING.value
PLAN_STAGE = JobStatus.PLANNING.value
VIDEO_STAGE = JobStatus.GENERATING_VIDEO.value
VOICE_STAGE = JobStatus.GENERATING_VOICE.value
MUSIC_STAGE = JobStatus.GENERATING_MUSIC.value
COMPOSE_STAGE = JobStatus.COMPOSING.value
EXPORT_STAGE = JobStatus.EXPORTING.value


@dataclass
class RunJobOptions:
    resume: bool = False


@dataclass
class StageResult:
    value: Any
    outputs: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    resumed: bool = False


class JobOrchestrator:
    async def run(self, job_id: str, options: RunJobOptions | None = None) -> dict[str, object]:
        options = options or RunJobOptions()

        async with AsyncSessionLocal() as session:
            job = await self._load_job(session, job_id)
            if job is None:
                raise LookupError(f"Job not found: {job_id}")

            self._validate_provider_policy(job)
            job_dirs = ensure_job_storage(job.id)
            state = PipelineStateManager(job.id, job_dirs["data"] / "pipeline_state.json")

            if options.resume:
                if not state.path.exists():
                    await self._log(session, job.id, "resume", "No pipeline state found; starting fresh")
                    await self._reset_outputs(session, job)
                    state.reset()
                else:
                    job.started_at = job.started_at or datetime.utcnow()
                    await session.commit()
                    await self._log(session, job.id, "resume", "Resuming job from pipeline state")
            else:
                await self._reset_outputs(session, job)
                state.reset()

            try:
                ingest = await self._stage_ingest(session, job, job_dirs, state, options.resume)
                analysis = await self._stage_analysis(session, job, job_dirs, state, ingest, options.resume)
                script = await self._stage_script(session, job, job_dirs, state, analysis, options.resume)
                shots = await self._stage_planning(session, job, job_dirs, state, analysis, script, options.resume)

                await self._set_status(session, job, JobStatus.GENERATING_VIDEO)
                parallel_results = await asyncio.gather(
                    self._stage_video(job, job_dirs, state, shots, options.resume),
                    self._stage_voice(job, job_dirs, state, shots, script, options.resume),
                    self._stage_music(job, job_dirs, state, analysis, options.resume),
                    return_exceptions=True,
                )
                self._raise_parallel_failures(parallel_results)
                video_assets, voice_assets, music_asset = parallel_results  # type: ignore[assignment]

                composition = await self._stage_compose(
                    session,
                    job,
                    job_dirs,
                    state,
                    shots,
                    script,
                    video_assets,
                    voice_assets,
                    music_asset,
                    options.resume,
                )
                export = await self._stage_export(
                    session,
                    job,
                    job_dirs,
                    state,
                    analysis,
                    script,
                    shots,
                    composition,
                    options.resume,
                )

                payload = {
                    **export.value.model_dump(),
                    "pipeline_state_path": to_workspace_path(state.path),
                }
                job.status = JobStatus.DONE
                job.finished_at = datetime.utcnow()
                job.result_json = payload
                await session.commit()
                await self._log(session, job.id, "export", "Job completed")
                return payload
            except Exception as exc:
                stage = state.current_stage() or "pipeline"
                state.mark_failed(stage, str(exc))
                job.status = JobStatus.FAILED
                job.finished_at = datetime.utcnow()
                job.result_json = {
                    "error": str(exc),
                    "pipeline_state_path": to_workspace_path(state.path),
                }
                await session.commit()
                await self._log(session, job.id, "failed", str(exc), level="error")
                raise

    async def _stage_ingest(
        self,
        session,
        job: Job,
        job_dirs: dict[str, Path],
        state: PipelineStateManager,
        resume: bool,
    ) -> StageResult:
        if resume and state.is_completed(INGEST_STAGE):
            return self._load_ingest_result(job_dirs, state)

        await self._set_status(session, job, JobStatus.INGESTING)
        state.mark_running(INGEST_STAGE)
        ingest_result = await asyncio.to_thread(
            IngestService().run,
            trend_source=job.trend_source,
            job=job,
            job_dirs=job_dirs,
        )
        if ingest_result.source_path:
            await self._record_asset(
                session,
                job.id,
                AssetType.SOURCE_VIDEO,
                ingest_result.source_path,
                ingest_result.source_meta,
            )
        meta_path = to_workspace_path(job_dirs["data"] / "source_meta.json")
        await self._record_asset(session, job.id, AssetType.SOURCE_META, meta_path, ingest_result.source_meta)
        await self._log(session, job.id, "ingest", "Source prepared")

        outputs = ([ingest_result.source_path] if ingest_result.source_path else []) + [meta_path, *ingest_result.frames]
        details = {"source_path": ingest_result.source_path, "frames": ingest_result.frames, "source_meta_path": meta_path}
        state.mark_completed(INGEST_STAGE, outputs=outputs, details=details)
        return StageResult(value=ingest_result, outputs=outputs, details=details)

    async def _stage_analysis(
        self,
        session,
        job: Job,
        job_dirs: dict[str, Path],
        state: PipelineStateManager,
        ingest: StageResult,
        resume: bool,
    ) -> StageResult:
        if resume and state.is_completed(ANALYZE_STAGE):
            return self._load_model_result(job_dirs["data"] / "trend_analysis.json", TrendAnalysis)

        await self._set_status(session, job, JobStatus.ANALYZING)
        state.mark_running(ANALYZE_STAGE)
        output_path = job_dirs["data"] / "trend_analysis.json"
        analysis = await asyncio.to_thread(
            TrendAnalyzerService().run,
            project=job.project,
            job=job,
            trend_source=job.trend_source,
            ingest_result=ingest.value,
            output_path=output_path,
        )
        output_ref = to_workspace_path(output_path)
        await self._record_asset(session, job.id, AssetType.TREND_ANALYSIS, output_ref, analysis.model_dump())
        await self._log(session, job.id, "analyze", "Trend structure extracted")
        state.mark_completed(ANALYZE_STAGE, outputs=[output_ref], details={"analysis_path": output_ref})
        return StageResult(value=analysis, outputs=[output_ref], details={"analysis_path": output_ref})

    async def _stage_script(
        self,
        session,
        job: Job,
        job_dirs: dict[str, Path],
        state: PipelineStateManager,
        analysis: StageResult,
        resume: bool,
    ) -> StageResult:
        if resume and state.is_completed(SCRIPT_STAGE):
            return self._load_model_result(job_dirs["data"] / "script.json", ScriptPackage)

        await self._set_status(session, job, JobStatus.SCRIPTING)
        state.mark_running(SCRIPT_STAGE)
        output_path = job_dirs["data"] / "script.json"
        script = await asyncio.to_thread(
            ScriptGeneratorService(get_script_provider(job.config_json.get("script_provider", "template"))).run,
            project=job.project,
            job=job,
            analysis=analysis.value,
            output_path=output_path,
        )
        output_ref = to_workspace_path(output_path)
        await self._record_asset(session, job.id, AssetType.SCRIPT, output_ref, script.model_dump())
        await self._log(session, job.id, "script", "Script generated")
        state.mark_completed(SCRIPT_STAGE, outputs=[output_ref], details={"script_path": output_ref})
        return StageResult(value=script, outputs=[output_ref], details={"script_path": output_ref})

    async def _stage_planning(
        self,
        session,
        job: Job,
        job_dirs: dict[str, Path],
        state: PipelineStateManager,
        analysis: StageResult,
        script: StageResult,
        resume: bool,
    ) -> StageResult:
        if resume and state.is_completed(PLAN_STAGE):
            shots = self._load_shots(job, job_dirs["data"] / "shot_plan.json")
            return StageResult(value=shots, outputs=state.stage_outputs(PLAN_STAGE), resumed=True)

        await self._set_status(session, job, JobStatus.PLANNING)
        state.mark_running(PLAN_STAGE)
        output_path = job_dirs["data"] / "shot_plan.json"
        shots = await asyncio.to_thread(
            ShotPlannerService().run,
            project=job.project,
            job=job,
            analysis=analysis.value,
            script=script.value,
            output_path=output_path,
        )
        await self._replace_shots(session, job.id, shots)
        output_ref = to_workspace_path(output_path)
        await self._record_asset(session, job.id, AssetType.SHOT_PLAN, output_ref, {"shot_count": len(shots)})
        await self._log(session, job.id, "planning", f"Planned {len(shots)} shots")
        shot_outputs = [output_ref]
        state.mark_completed(PLAN_STAGE, outputs=shot_outputs, details={"shot_count": len(shots), "shot_plan_path": output_ref})
        return StageResult(value=shots, outputs=shot_outputs, details={"shot_plan_path": output_ref})

    async def _stage_video(
        self,
        job: Job,
        job_dirs: dict[str, Path],
        state: PipelineStateManager,
        shots: StageResult,
        resume: bool,
    ) -> StageResult:
        if resume and state.is_completed(VIDEO_STAGE):
            outputs = state.stage_outputs(VIDEO_STAGE)
            artifacts = [MediaArtifact(path=path, metadata={"order": index + 1}) for index, path in enumerate(outputs)]
            return StageResult(value=artifacts, outputs=outputs, resumed=True)

        state.mark_running(VIDEO_STAGE)
        try:
            artifacts = await asyncio.to_thread(
                VideoGenerationService(get_video_provider(job.config_json.get("video_provider", "comfyui"))).run,
                project=job.project,
                job=job,
                shots=shots.value,
                job_dirs=job_dirs,
            )
            async with AsyncSessionLocal() as session:
                for artifact in artifacts:
                    await self._record_asset(session, job.id, AssetType.VIDEO_CLIP, artifact.path, artifact.metadata)
                await self._log(session, job.id, "video", f"Generated {len(artifacts)} clips")
            outputs = [artifact.path for artifact in artifacts]
            state.mark_completed(VIDEO_STAGE, outputs=outputs, details={"clip_count": len(outputs)})
            return StageResult(value=artifacts, outputs=outputs, details={"clip_count": len(outputs)})
        except Exception as exc:
            state.mark_failed(VIDEO_STAGE, str(exc))
            raise

    async def _stage_voice(
        self,
        job: Job,
        job_dirs: dict[str, Path],
        state: PipelineStateManager,
        shots: StageResult,
        script: StageResult,
        resume: bool,
    ) -> StageResult:
        if resume and state.is_completed(VOICE_STAGE):
            outputs = [path for path in state.stage_outputs(VOICE_STAGE) if path.endswith(".wav")]
            artifacts = [MediaArtifact(path=path, metadata={"order": index + 1}) for index, path in enumerate(outputs)]
            return StageResult(value=artifacts, outputs=state.stage_outputs(VOICE_STAGE), resumed=True)

        state.mark_running(VOICE_STAGE)
        try:
            artifacts = await asyncio.to_thread(
                VoiceGenerationService(get_tts_provider(job.config_json.get("tts_provider", "stub"))).run,
                project=job.project,
                job=job,
                shots=shots.value,
                script=script.value,
                job_dirs=job_dirs,
            )
            async with AsyncSessionLocal() as session:
                for artifact in artifacts:
                    await self._record_asset(session, job.id, AssetType.VOICE_TRACK, artifact.path, artifact.metadata)
                await self._log(session, job.id, "voice", f"Generated {len(artifacts)} voice scenes")
            outputs = [artifact.path for artifact in artifacts]
            voiceover_txt_path = job_dirs["voice"] / "voiceover.txt"
            if voiceover_txt_path.exists():
                outputs.append(to_workspace_path(voiceover_txt_path))
            state.mark_completed(VOICE_STAGE, outputs=outputs, details={"voice_scene_count": len(artifacts)})
            return StageResult(value=artifacts, outputs=outputs, details={"voice_scene_count": len(artifacts)})
        except Exception as exc:
            state.mark_failed(VOICE_STAGE, str(exc))
            raise

    async def _stage_music(
        self,
        job: Job,
        job_dirs: dict[str, Path],
        state: PipelineStateManager,
        analysis: StageResult,
        resume: bool,
    ) -> StageResult:
        if resume and state.is_completed(MUSIC_STAGE):
            outputs = state.stage_outputs(MUSIC_STAGE)
            artifact = MediaArtifact(path=outputs[0], metadata={}) if outputs else None
            return StageResult(value=artifact, outputs=outputs, resumed=True)

        state.mark_running(MUSIC_STAGE)
        try:
            artifact = await asyncio.to_thread(
                MusicGenerationService(get_music_provider(job.config_json.get("music_provider", "library"))).run,
                project=job.project,
                job=job,
                analysis=analysis.value,
                job_dirs=job_dirs,
            )
            async with AsyncSessionLocal() as session:
                await self._record_asset(session, job.id, AssetType.MUSIC_TRACK, artifact.path, artifact.metadata)
                await self._log(session, job.id, "music", "Music track prepared")
            outputs = [artifact.path]
            state.mark_completed(MUSIC_STAGE, outputs=outputs, details={"music_track": artifact.path})
            return StageResult(value=artifact, outputs=outputs, details={"music_track": artifact.path})
        except Exception as exc:
            state.mark_failed(MUSIC_STAGE, str(exc))
            raise

    async def _stage_compose(
        self,
        session,
        job: Job,
        job_dirs: dict[str, Path],
        state: PipelineStateManager,
        shots: StageResult,
        script: StageResult,
        video_assets: StageResult,
        voice_assets: StageResult,
        music_asset: StageResult,
        resume: bool,
    ) -> StageResult:
        if resume and state.is_completed(COMPOSE_STAGE):
            details = state.stage_details(COMPOSE_STAGE)
            return StageResult(value=details, outputs=state.stage_outputs(COMPOSE_STAGE), details=details, resumed=True)

        await self._set_status(session, job, JobStatus.COMPOSING)
        state.mark_running(COMPOSE_STAGE)
        composition = await asyncio.to_thread(
            ComposerService().run,
            project=job.project,
            job=job,
            shots=shots.value,
            script=script.value,
            video_assets=video_assets.value,
            voice_assets=voice_assets.value,
            music_asset=music_asset.value,
            job_dirs=job_dirs,
        )
        await self._record_asset(session, job.id, AssetType.COMPOSED_VIDEO, str(composition["composed_video"]), composition)
        await self._record_asset(session, job.id, AssetType.SUBTITLE, str(composition["subtitles"]), {})
        await self._log(session, job.id, "compose", "Composition assembled")
        outputs = [value for value in composition.values() if value]
        state.mark_completed(COMPOSE_STAGE, outputs=outputs, details=composition)
        return StageResult(value=composition, outputs=outputs, details=composition)

    async def _stage_export(
        self,
        session,
        job: Job,
        job_dirs: dict[str, Path],
        state: PipelineStateManager,
        analysis: StageResult,
        script: StageResult,
        shots: StageResult,
        composition: StageResult,
        resume: bool,
    ) -> StageResult:
        if resume and state.is_completed(EXPORT_STAGE):
            details = state.stage_details(EXPORT_STAGE)
            return StageResult(value=ExportArtifacts.model_validate(details), outputs=state.stage_outputs(EXPORT_STAGE), details=details, resumed=True)

        await self._set_status(session, job, JobStatus.EXPORTING)
        state.mark_running(EXPORT_STAGE)
        export = await asyncio.to_thread(
            ExporterService().run,
            project=job.project,
            job=job,
            analysis=analysis.value,
            script=script.value,
            shots=shots.value,
            composition=composition.value,
            job_dirs=job_dirs,
        )
        await self._record_asset(session, job.id, AssetType.FINAL_VIDEO, export.final_video, {})
        if export.preview_image:
            await self._record_asset(session, job.id, AssetType.THUMBNAIL, export.preview_image, {})
        await self._record_asset(session, job.id, AssetType.METADATA, export.metadata_json, export.model_dump())
        outputs = [item for item in [export.final_video, export.subtitles, export.preview_image, export.metadata_json] if item]
        state.mark_completed(EXPORT_STAGE, outputs=outputs, details=export.model_dump())
        return StageResult(value=export, outputs=outputs, details=export.model_dump())

    def _load_ingest_result(self, job_dirs: dict[str, Path], state: PipelineStateManager) -> StageResult:
        details = state.stage_details(INGEST_STAGE)
        meta_path = resolve_local_path(details["source_meta_path"])
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        ingest = IngestResult(
            source_path=str(details.get("source_path") or ""),
            frames=list(details.get("frames") or []),
            source_meta=payload,
        )
        return StageResult(value=ingest, outputs=state.stage_outputs(INGEST_STAGE), details=details, resumed=True)

    def _load_model_result(self, path: Path, model_cls) -> StageResult:
        payload = json.loads(path.read_text(encoding="utf-8"))
        model = model_cls.model_validate(payload)
        return StageResult(value=model, outputs=[to_workspace_path(path)], resumed=True)

    def _load_shots(self, job: Job, path: Path) -> list[ShotSpec]:
        if job.shots:
            return [
                ShotSpec(
                    order=shot.shot_order,
                    duration_sec=shot.duration_sec,
                    type=shot.shot_type,
                    prompt=shot.prompt,
                    camera=shot.camera,
                    motion=shot.motion,
                    overlay=shot.overlay_text,
                    transition=shot.transition_name,
                    metadata=shot.metadata_json,
                )
                for shot in job.shots
            ]

        payload = json.loads(path.read_text(encoding="utf-8"))
        return [ShotSpec.model_validate(item) for item in payload.get("shots", [])]

    def _raise_parallel_failures(self, results: list[object]) -> None:
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise errors[0]

    def _validate_provider_policy(self, job: Job) -> None:
        provider_name = str(job.config_json.get("video_provider", "comfyui"))
        if is_synthetic_video_provider(provider_name) and not bool(job.config_json.get("allow_synthetic_video")):
            raise RuntimeError(
                "Synthetic video provider is disabled for production jobs. "
                "Use video_provider='comfyui' or explicitly set allow_synthetic_video=true for smoke/demo runs."
            )

    async def _load_job(self, session, job_id: str) -> Job | None:
        result = await session.execute(
            select(Job)
            .where(Job.id == job_id)
            .options(
                selectinload(Job.project),
                selectinload(Job.trend_source),
                selectinload(Job.shots),
                selectinload(Job.assets),
                selectinload(Job.logs),
            )
        )
        return result.scalar_one_or_none()

    async def _reset_outputs(self, session, job: Job) -> None:
        await session.execute(delete(JobShot).where(JobShot.job_id == job.id))
        await session.execute(delete(Asset).where(Asset.job_id == job.id))
        await session.execute(delete(LogEntry).where(LogEntry.job_id == job.id))
        job.result_json = {}
        job.started_at = datetime.utcnow()
        job.finished_at = None
        await session.commit()

    async def _set_status(self, session, job: Job, status: JobStatus) -> None:
        job.status = status
        if status == JobStatus.INGESTING and job.started_at is None:
            job.started_at = datetime.utcnow()
        await session.commit()

    async def _replace_shots(self, session, job_id: str, shots: list[ShotSpec]) -> None:
        for shot in shots:
            session.add(
                JobShot(
                    job_id=job_id,
                    shot_order=shot.order,
                    shot_type=shot.type,
                    duration_sec=shot.duration_sec,
                    prompt=shot.prompt,
                    camera=shot.camera,
                    motion=shot.motion,
                    overlay_text=shot.overlay,
                    transition_name=shot.transition,
                    metadata_json=shot.metadata,
                )
            )
        await session.commit()

    async def _record_asset(
        self,
        session,
        job_id: str,
        asset_type: AssetType,
        path: str,
        metadata_json: dict[str, object],
    ) -> None:
        session.add(
            Asset(
                job_id=job_id,
                asset_type=asset_type,
                path=path,
                metadata_json=metadata_json,
            )
        )
        await session.commit()

    async def _log(self, session, job_id: str, stage: str, message: str, level: str = "info") -> None:
        session.add(LogEntry(job_id=job_id, stage=stage, level=level, message=message, metadata_json={}))
        await session.commit()


async def run_job_pipeline(job_id: str, *, resume: bool = False) -> dict[str, object]:
    return await JobOrchestrator().run(job_id, options=RunJobOptions(resume=resume))
