from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Prismalis Backend"
    environment: str = "development"
    debug: bool = False
    allowed_origins: list[str] = ["*"]

    # FMP
    fmp_api_key: str
    fmp_base_url: str = "https://financialmodelingprep.com/"
    fmp_api_version: str = "stable"
    fmp_timeout_seconds: float = 20.0
    fmp_max_retries: int = 2

    # Database
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600

    # JWT — no default so startup fails loudly when unset
    jwt_secret_key: str
    jwt_issuer: str = "prismalis-backend"
    access_token_expire_minutes: int = 1440

    # Google OAuth (optional)
    google_client_id: str = ""

    @field_validator("jwt_secret_key")
    @classmethod
    def _jwt_secret_not_default(cls, v: str) -> str:
        if v in ("", "change-this-secret-key"):
            raise ValueError("JWT_SECRET_KEY must be set to a strong random secret")
        return v

    @field_validator("database_url")
    @classmethod
    def _database_url_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL must be set")
        return v

    @field_validator("fmp_api_key")
    @classmethod
    def _fmp_key_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("FMP_API_KEY must be set")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
