from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.core.config import settings


JOB_SUBDIRS = (
    "source",
    "frames",
    "shots",
    "voice",
    "music",
    "subtitles",
    "output",
    "data",
    "temp",
)


def safe_slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return normalized.strip("_") or "item"


def ensure_base_storage() -> None:
    for path in (
        settings.storage_root,
        settings.input_root,
        settings.jobs_root,
        settings.assets_root,
        settings.assets_root / "logos",
        settings.assets_root / "fonts",
        settings.assets_root / "music_library",
        settings.assets_root / "uploads",
        settings.input_root / "trends",
    ):
        path.mkdir(parents=True, exist_ok=True)


def ensure_job_storage(job_id: str) -> dict[str, Path]:
    job_root = settings.jobs_root / job_id
    job_root.mkdir(parents=True, exist_ok=True)
    job_dirs = {"root": job_root}
    for name in JOB_SUBDIRS:
        path = job_root / name
        path.mkdir(parents=True, exist_ok=True)
        job_dirs[name] = path
    return job_dirs


def trend_upload_dir(trend_id: str) -> Path:
    path = settings.input_root / "trends" / trend_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_file(source_path: Path, destination_path: Path) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)
    return destination_path


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def resolve_local_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def to_workspace_path(path: str | Path) -> str:
    candidate = Path(path).resolve()
    try:
        return str(candidate.relative_to(Path.cwd()))
    except ValueError:
        return str(candidate)
