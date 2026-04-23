from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import TrendSourceType


class TrendSourceCreate(BaseModel):
    type: TrendSourceType = TrendSourceType.VIDEO
    source_path: str
    hook_description: str | None = None
    structure_detected: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class TrendSourceUpdate(BaseModel):
    type: TrendSourceType = TrendSourceType.VIDEO
    source_path: str
    hook_description: str | None = None
    structure_detected: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class TrendSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: TrendSourceType
    source_path: str
    hook_description: str | None = None
    structure_detected: bool
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
