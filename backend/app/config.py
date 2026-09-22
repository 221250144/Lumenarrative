from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/xuguangji.db"
    data_dir: Path = Path("./data")
    queue_mode: str = "local"
    redis_url: str = "redis://localhost:6379/0"
    model_provider: str = "mock"
    model_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_api_key: str = ""
    vlm_model: str = "qwen3-vl-plus"
    llm_model: str = "qwen-plus"
    model_timeout_s: int = 90
    model_concurrency: int = 2
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
