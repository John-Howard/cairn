import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_secret: str
    auth_mode: str
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "sqlite:///cairn.db"),
        session_secret=os.environ.get("SESSION_SECRET", "dev-secret-change-me"),
        auth_mode=os.environ.get("AUTH_MODE", "dev"),
        oidc_issuer=os.environ.get("OIDC_ISSUER", ""),
        oidc_client_id=os.environ.get("OIDC_CLIENT_ID", ""),
        oidc_client_secret=os.environ.get("OIDC_CLIENT_SECRET", ""),
    )
