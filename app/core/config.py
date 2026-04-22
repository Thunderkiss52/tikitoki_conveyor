from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    PROJECT_NAME: str = "Tikitoki Conveyor"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost/tikitoki"
    REDIS_URL: str = "redis://localhost:6379/0"
    JOB_QUEUE_NAME: str = "video_jobs"

    STORAGE_BASE_PATH: str = "storage"
    INPUT_DIR_NAME: str = "input"
    JOBS_DIR_NAME: str = "jobs"
    ASSETS_DIR_NAME: str = "assets"

    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"

    DEFAULT_VIDEO_PROVIDER: str = "comfyui"
    DEFAULT_TTS_PROVIDER: str = "stub"
    DEFAULT_MUSIC_PROVIDER: str = "library"
    DEFAULT_SCRIPT_PROVIDER: str = "template"

    COMFYUI_BASE_URL: str = "http://127.0.0.1:8188"
    COMFYUI_TIMEOUT_SEC: int = 600
    COMFYUI_POLL_INTERVAL_SEC: float = 2.0
    COMFYUI_WORKFLOW_TEMPLATE: str = "app/templates/comfyui/workflow_api.example.json"

    DEFAULT_ASPECT: str = "9:16"
    DEFAULT_WIDTH: int = 1080
    DEFAULT_HEIGHT: int = 1920
    DEFAULT_DURATION_SEC: int = 8
    DEFAULT_SCENE_COUNT: int = 3
    DEFAULT_PLATFORM: str = "tiktok"
    DEFAULT_LANGUAGE: str = "ru"

    @property
    def storage_root(self) -> Path:
        return Path(self.STORAGE_BASE_PATH).resolve()

    @property
    def input_root(self) -> Path:
        return self.storage_root / self.INPUT_DIR_NAME

    @property
    def jobs_root(self) -> Path:
        return self.storage_root / self.JOBS_DIR_NAME

    @property
    def assets_root(self) -> Path:
        return self.storage_root / self.ASSETS_DIR_NAME


settings = Settings()
