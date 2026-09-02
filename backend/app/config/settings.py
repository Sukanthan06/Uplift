from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    policy_version: str = "v1"
    env: str = "development"

    # Action service backend selection. "mock" (default): deterministic,
    # no external calls. "razorpay_test": real HTTP to Razorpay's sandbox,
    # test-mode credentials only. "off": shadow mode, logs the intended
    # action, calls nothing.
    action_mode: Literal["mock", "razorpay_test", "off"] = "mock"
    razorpay_api_key: str = ""
    razorpay_api_secret: str = ""
    razorpay_test_endpoint: str = "https://api.razorpay.com/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
