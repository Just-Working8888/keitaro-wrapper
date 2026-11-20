from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    keitaro_url: str = "https://tlgk.host"
    keitaro_api_key: str = ""
    keitaro_timeout: float = 30.0

    database_url: str = "sqlite:///./keitaro_wrapper.db"

    default_domain_id: Optional[int] = None
    default_group_id: Optional[int] = None
    default_traffic_source_id: Optional[int] = None

    geo_redirect_url: str = "https://www.google.com"

    demo_mode: bool = False  # set by app/demo.py only


@lru_cache
def get_settings() -> Settings:
    return Settings()
