"""RQ CLI configuration; credentials remain in the mounted Swarm secret."""

from pathlib import Path
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RQ_")
    redis_host: str = "main-storage_redis"
    redis_db: int = 10
    password_file: Path = Path("/run/secrets/redis_password")


settings = Settings()
REDIS_URL = (
    f"redis://:{quote(settings.password_file.read_text().strip(), safe='')}"
    f"@{settings.redis_host}:6379/{settings.redis_db}"
)
