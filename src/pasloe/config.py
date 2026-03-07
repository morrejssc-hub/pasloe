from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database configuration
    # Default to local sqlite for development/testing
    database_url: str = "sqlite+aiosqlite:///./events.db"
    
    # API configuration
    host: str = "0.0.0.0"
    port: int = 8000
    api_key: str | None = None
    
    # Environment name
    env: str = "dev"
    
    # S3 Configuration for artifact uploads
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_db_url() -> str:
    return get_settings().database_url

def is_sqlite() -> bool:
    return get_db_url().startswith("sqlite")
