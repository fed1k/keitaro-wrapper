from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    keitaro_url: str = "https://tlgk.host"
    keitaro_api_key: str = ""

    # Defaults applied to every campaign created by the creator.
    keitaro_domain_id: int = 1813
    keitaro_group_id: int = 10332
    keitaro_traffic_source_id: int = 836

    campaign_prefix: str = "test_allamurotov_"
    google_url: str = "https://google.com"
    report_timezone: str = "Europe/Moscow"

    database_url: str = "sqlite:///./keitaro_wrapper.db"

    @property
    def api_base(self) -> str:
        return self.keitaro_url.rstrip("/") + "/admin_api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
