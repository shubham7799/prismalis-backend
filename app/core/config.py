import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = "Prismalis Backend"
    fmp_api_key: str = os.getenv("FMP_API_KEY", "")
    fmp_base_url: str = os.getenv("FMP_BASE_URL", "https://financialmodelingprep.com/")
    fmp_api_version: str = os.getenv("FMP_API_VERSION", "stable")
    fmp_timeout_seconds: float = float(os.getenv("FMP_TIMEOUT_SECONDS", "20"))
    fmp_max_retries: int = int(os.getenv("FMP_MAX_RETRIES", "2"))
    database_url: str = os.getenv("DATABASE_URL", "")
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "change-this-secret-key")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "prismalis-backend")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
