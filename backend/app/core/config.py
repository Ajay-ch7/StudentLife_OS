from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    gemini_api_key: str = "changeme"
    gemini_model: str = "gemini-1.5-flash"
    gemini_timeout_seconds: int = 30
    database_url: str = "sqlite:///./data/sqlite/student_life_os.db"
    upload_dir: str = "./data/uploads"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
SQLITE_DIR = DATA_DIR / "sqlite"
UPLOAD_DIR = DATA_DIR / "uploads"
