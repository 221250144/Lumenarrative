from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/xuguangji.db"
    db_pool_size: int = Field(default=2, ge=1, le=10)
    db_max_overflow: int = Field(default=2, ge=0, le=10)
    data_dir: Path = Path("./data")
    queue_mode: str = "local"
    auth_session_days: int = Field(default=14, ge=1, le=90)
    auth_cookie_secure: bool = False
    redis_url: str = "redis://localhost:6379/0"
    model_provider: str = "mock"
    model_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_api_key: str = ""
    vlm_model: str = "qwen3.8-max"
    llm_model: str = "qwen-plus"
    model_timeout_s: int = Field(default=900, ge=0)
    model_concurrency: int = Field(default=8, ge=1, le=32)
    media_concurrency: int = Field(default=2, ge=1, le=8)
    ffmpeg_threads: int = Field(default=4, ge=1, le=32)
    video_generation_enabled: bool = True
    video_generation_model: str = "happyhorse-1.1-i2v"
    video_generation_base_url: str = ""
    video_generation_concurrency: int = Field(default=1, ge=1, le=5)
    video_generation_poll_s: float = Field(default=15, ge=1, le=60)
    video_generation_timeout_s: int = Field(default=900, ge=30, le=3600)
    asr_base_url: str = ""
    asr_api_key: str = ""
    asr_model: str = ""
    max_upload_mb: int = 256
    max_assets: int = 20
    max_project_duration_s: float = 600
    window_s: float = 8
    overlap_s: float = 2
    sample_fps: float = 1
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
