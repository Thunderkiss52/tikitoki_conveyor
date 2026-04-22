from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectConfig(BaseModel):
    logo_path: str | None = None
    brand_colors: list[str] = Field(default_factory=list)
    voice_style: str = "calm_dark_male"
    music_style: str = "dark cyber tension"
    default_aspect: str = "9:16"
    extra: dict[str, Any] = Field(default_factory=dict)

    def as_db_config(self) -> dict[str, Any]:
        base = self.model_dump(exclude={"extra"})
        return {**base, **self.extra}


class ProjectCreate(BaseModel):
    name: str
    config: ProjectConfig = Field(default_factory=ProjectConfig)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    config_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime
