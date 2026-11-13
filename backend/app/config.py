from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения / файла .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Keitaro
    keitaro_url: str = ""
    keitaro_api_key: str = ""
    keitaro_timeout: float = 30.0

    # Правила для новых кампаний
    campaign_prefix: str = ""
    google_redirect_url: str = "https://www.google.com"
    keitaro_domain: str = ""
    keitaro_group_name: str = "FORTESTS"
    keitaro_source_name: str = "FORTESTS"
    country_filter_name: str = ""

    # Приложение
    database_url: str = "sqlite:///./data/app.db"
    offers_cache_ttl: int = 300

    @property
    def keitaro_configured(self) -> bool:
        return bool(self.keitaro_url.strip() and self.keitaro_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
