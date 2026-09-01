from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    policy_version: str = "v1"
    env: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
