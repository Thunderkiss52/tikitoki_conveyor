from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.storage import write_json


def utc_now() -> str:
    return datetime.utcnow().isoformat()


class PipelineStateManager:
    def __init__(self, job_id: str, path: Path) -> None:
        self.job_id = job_id
        self.path = path
        self.payload = self._load()

    def reset(self) -> None:
        self.payload = self._empty_payload()
        self.save()

    def is_completed(self, stage: str) -> bool:
        entry = self.payload.get("stages", {}).get(stage, {})
        return entry.get("status") == "completed"

    def current_stage(self) -> str | None:
        return self.payload.get("current_stage")

    def mark_running(self, stage: str) -> None:
        entry = self._stage_entry(stage)
        entry["status"] = "running"
        entry["started_at"] = entry.get("started_at") or utc_now()
        entry["finished_at"] = None
        entry["error"] = None
        self.payload["current_stage"] = stage
        self.payload["updated_at"] = utc_now()
        self.save()

    def mark_completed(
        self,
        stage: str,
        outputs: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        entry = self._stage_entry(stage)
        entry["status"] = "completed"
        entry["started_at"] = entry.get("started_at") or utc_now()
        entry["finished_at"] = utc_now()
        entry["error"] = None
        entry["outputs"] = outputs or []
        entry["details"] = details or {}
        self.payload["current_stage"] = stage
        self.payload["updated_at"] = utc_now()
        self.save()

    def mark_failed(self, stage: str, error: str) -> None:
        entry = self._stage_entry(stage)
        entry["status"] = "failed"
        entry["started_at"] = entry.get("started_at") or utc_now()
        entry["finished_at"] = utc_now()
        entry["error"] = error
        self.payload["current_stage"] = stage
        self.payload["updated_at"] = utc_now()
        self.save()

    def stage_outputs(self, stage: str) -> list[str]:
        entry = self.payload.get("stages", {}).get(stage, {})
        outputs = entry.get("outputs") or []
        return [str(item) for item in outputs]

    def stage_details(self, stage: str) -> dict[str, Any]:
        entry = self.payload.get("stages", {}).get(stage, {})
        details = entry.get("details") or {}
        return dict(details)

    def save(self) -> None:
        write_json(self.path, self.payload)

    def _stage_entry(self, stage: str) -> dict[str, Any]:
        stages = self.payload.setdefault("stages", {})
        return stages.setdefault(
            stage,
            {
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "error": None,
                "outputs": [],
                "details": {},
            },
        )

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            import json

            return json.loads(self.path.read_text(encoding="utf-8"))
        return self._empty_payload()

    def _empty_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "current_stage": None,
            "updated_at": utc_now(),
            "stages": {},
        }
