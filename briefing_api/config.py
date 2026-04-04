from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Base
    environment: str = "development"
    api_port: int = 8002

    # Database
    database_url: str

    # API security
    api_key: str = "dev-key-change-in-production"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
