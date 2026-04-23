from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from fastapi import Body
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import GenerationMode, JobStatus, TrendSourceType
from app.core.render_presets import (
    COMFYUI_WORKFLOWS,
    GENERATION_MODE_CHOICES,
    MODE_DEFAULTS,
    QUALITY_PRESET_CHOICES,
    QUALITY_PRESETS,
)
from app.db.session import get_session
from app.schemas.job import JobCreate, JobDetail
from app.schemas.project import ProjectCreate
from app.schemas.trend import TrendSourceCreate
from app.schemas.ui_prompt import PromptAssetSelection, PromptGenerateRequest, PromptPlanRequest, PromptPlanResponse
from app.services.jobs import JobService, run_job_pipeline
from app.services.jobs.service import DEFAULT_JOB_CONFIG
from app.services.projects.service import ProjectService
from app.services.prompting import PromptPlanningService
from app.services.trends.service import TrendSourceService
from app.utils.asset_library import (
    DISCOVERABLE_EXTENSIONS,
    LOGO_MODE_CHOICES,
    asset_static_url,
    delete_managed_asset,
    detect_media_type,
    is_mutable_asset,
    normalize_logo_upload,
)
from app.utils.storage import resolve_local_path, safe_slug, to_workspace_path
from app.workers.queue import enqueue_job


router = APIRouter(prefix="/ui", tags=["ui"])

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "content_templates.json"

UPLOAD_KIND_TARGETS = {
    "logo": "logos",
    "reference": "uploads",
    "music": "music_library",
}

DISCOVERABLE_PATHS: tuple[tuple[str, Path], ...] = (
    ("builtin", Path.cwd() / "HODOR.jpg"),
    ("logo", settings.assets_root / "logos"),
    ("reference", settings.assets_root / "uploads"),
    ("music", settings.assets_root / "music_library"),
    ("trend_demo", settings.input_root / "demo"),
    ("trend_upload", settings.input_root / "trends"),
)


class AssetDeleteRequest(BaseModel):
    path: str


@router.get("/options")
async def get_ui_options() -> dict[str, object]:
    templates = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return {
        "providers": {
            "video": ["reference", "comfyui", "stub", "synthetic", "runway", "luma"],
            "tts": ["stub", "piper", "elevenlabs", "xtts"],
            "music": ["library", "hybrid", "generate", "stub"],
            "script": ["template", "openai", "anthropic"],
        },
        "defaults": {
            "project": {
                "voice_style": "calm_dark_male",
                "music_style": "dark cyber tension",
                "default_aspect": settings.DEFAULT_ASPECT,
                "brand_colors": ["#0A1633", "#132A63"],
            },
            "job": {
                **DEFAULT_JOB_CONFIG,
                "mode": GenerationMode.REFERENCE_BASED.value,
                "duration_sec": settings.DEFAULT_DURATION_SEC,
                "language": settings.DEFAULT_LANGUAGE,
                "target_platform": settings.DEFAULT_PLATFORM,
                "scene_count": settings.DEFAULT_SCENE_COUNT,
                "aspect": settings.DEFAULT_ASPECT,
                "export_resolution": "",
                "quality_preset": settings.COMFYUI_DEFAULT_QUALITY_PRESET,
            },
        },
        "templates": templates,
        "trend_types": [item.value for item in TrendSourceType],
        "generation_modes": [item.value for item in GenerationMode],
        "job_statuses": [item.value for item in JobStatus],
        "render_presets": {
            "generation_modes": list(GENERATION_MODE_CHOICES),
            "quality_presets": list(QUALITY_PRESET_CHOICES),
            "workflows": COMFYUI_WORKFLOWS,
            "mode_defaults": MODE_DEFAULTS,
            "quality_defaults": QUALITY_PRESETS,
        },
        "asset_upload_kinds": list(UPLOAD_KIND_TARGETS),
        "logo_modes": list(LOGO_MODE_CHOICES),
        "runtime": {
            "api_prefix": settings.API_V1_STR,
            "default_video_provider": settings.DEFAULT_VIDEO_PROVIDER,
            "default_tts_provider": settings.DEFAULT_TTS_PROVIDER,
            "default_music_provider": settings.DEFAULT_MUSIC_PROVIDER,
            "default_script_provider": settings.DEFAULT_SCRIPT_PROVIDER,
            "text_only_video_provider": settings.TEXT_ONLY_VIDEO_PROVIDER,
            "storage_base_url": "/storage",
        },
        "prompt_assistant": {
            "configured": bool(settings.OPENAI_API_KEY),
            "model": settings.OPENAI_PROMPT_MODEL,
        },
    }


@router.get("/assets")
async def list_ui_assets() -> dict[str, list[dict[str, object]]]:
    items: list[dict[str, object]] = []
    for kind, candidate in DISCOVERABLE_PATHS:
        if candidate.is_file():
            record = _asset_record(kind, candidate)
            if record is not None:
                items.append(record)
            continue
        if not candidate.exists():
            continue
        for file_path in sorted(path for path in candidate.rglob("*") if path.is_file()):
            record = _asset_record(kind, file_path)
            if record is not None:
                items.append(record)
    items.sort(key=lambda item: (str(item["kind"]), str(item["path"])))
    return {"items": items}


@router.post("/assets/upload", status_code=status.HTTP_201_CREATED)
async def upload_ui_asset(
    file: UploadFile = File(...),
    kind: str = Form(default="reference"),
    logo_mode: str = Form(default="auto_emblem"),
) -> dict[str, object]:
    target_folder = UPLOAD_KIND_TARGETS.get(kind)
    if target_folder is None:
        supported = ", ".join(sorted(UPLOAD_KIND_TARGETS))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported upload kind: {kind}. Expected one of: {supported}")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    target_dir = settings.assets_root / target_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    original_name = Path(file.filename or "asset.bin").name
    suffix = Path(original_name).suffix or ".bin"
    metadata: dict[str, object] = {}
    if kind == "logo":
        try:
            content, processed_suffix, metadata = normalize_logo_upload(content, logo_mode)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if processed_suffix:
            suffix = processed_suffix
    target_name = f"{safe_slug(Path(original_name).stem)}_{uuid4().hex[:8]}{suffix.lower()}"
    target_path = target_dir / target_name
    target_path.write_bytes(content)

    return {
        "kind": kind,
        "filename": original_name,
        "path": to_workspace_path(target_path),
        "url": asset_static_url(target_path),
        "size_bytes": target_path.stat().st_size,
        "media_type": detect_media_type(target_path),
        "metadata": metadata,
    }


@router.delete("/assets")
async def delete_ui_asset(payload: AssetDeleteRequest = Body(...)) -> dict[str, object]:
    try:
        deleted_path = delete_managed_asset(payload.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return {
        "deleted": True,
        "path": to_workspace_path(deleted_path),
    }


@router.post("/assistant/plan", response_model=PromptPlanResponse)
async def plan_prompt(payload: PromptPlanRequest = Body(...)) -> PromptPlanResponse:
    service = PromptPlanningService()
    return await asyncio.to_thread(service.plan, payload)


@router.post("/assistant/generate")
async def generate_from_prompt(
    payload: PromptGenerateRequest = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    if payload.plan is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prompt plan is missing. Run assistant planning first.")

    service = PromptPlanningService()
    assets = _normalize_selected_assets(payload.assets)
    plan = service.apply_draft_overrides(payload.plan, payload.draft, assets)
    unique_project_name = await _unique_project_name(session, plan.project_name)
    plan = plan.model_copy(update={"project_name": unique_project_name})
    shot_overrides = service.build_shot_overrides(plan, assets, payload.draft, payload.shot_overrides)

    try:
        project = await ProjectService.create(session, ProjectCreate.model_validate(service.create_project_payload(plan, assets)))
        trend_source = await TrendSourceService.create(session, TrendSourceCreate.model_validate(service.create_trend_payload(plan, assets)))
        job_payload = JobCreate.model_validate(
            service.create_job_payload(
                plan=plan,
                assets=assets,
                draft=payload.draft,
                project_id=project.id,
                trend_source_id=trend_source.id,
                shot_overrides=shot_overrides,
                enqueue=payload.enqueue,
                run_now=payload.run_now,
            )
        )
        job = await JobService.create(session, job_payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    job_id = job.id
    if payload.enqueue:
        try:
            enqueue_job(job_id)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    elif payload.run_now:
        await run_job_pipeline(job_id)
        session.expire_all()

    detail = await JobService.get_detail(session, job_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Job not available after creation")

    return {
        "plan": plan.model_dump(mode="json"),
        "project": {
            "id": project.id,
            "name": project.name,
        },
        "trend": {
            "id": trend_source.id,
            "type": trend_source.type.value,
            "source_path": trend_source.source_path,
        },
        "job": JobDetail.model_validate(detail).model_dump(mode="json"),
    }


def _asset_record(kind: str, path: Path) -> dict[str, object] | None:
    if path.suffix.lower() not in DISCOVERABLE_EXTENSIONS:
        return None
    media_type = detect_media_type(path)
    return {
        "kind": kind,
        "name": path.name,
        "path": to_workspace_path(path),
        "url": asset_static_url(path),
        "size_bytes": path.stat().st_size,
        "media_type": media_type,
        "deletable": is_mutable_asset(path),
        "assignable_as_logo": media_type == "image",
        "assignable_as_trend": media_type == "video",
        "assignable_as_reference": kind in {"reference", "logo", "trend_demo", "trend_upload"} and media_type in {"image", "video"},
    }


def _normalize_selected_assets(assets: PromptAssetSelection) -> PromptAssetSelection:
    def normalize(raw_value: str | None) -> str | None:
        if not raw_value:
            return None
        path = resolve_local_path(raw_value)
        if not path.exists():
            raise FileNotFoundError(f"Asset not found: {path}")
        return to_workspace_path(path)

    return PromptAssetSelection(
        images=[item for item in [normalize(path) for path in assets.images] if item],
        reference_video_path=normalize(assets.reference_video_path),
        logo_path=normalize(assets.logo_path),
    )


async def _unique_project_name(session: AsyncSession, base_name: str) -> str:
    candidate = base_name.strip() or "Prompt Studio"
    if await ProjectService.get_by_name(session, candidate) is None:
        return candidate

    index = 2
    while True:
        next_candidate = f"{candidate} {index}"
        if await ProjectService.get_by_name(session, next_candidate) is None:
            return next_candidate
        index += 1
