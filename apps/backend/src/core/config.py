"""Application settings — strict Pydantic Settings, all from env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel default values. The bootstrap startup check refuses to run in
# production if any of these are still in effect.
INSECURE_DEFAULT_SECRET = "change-me-please"
INSECURE_DEFAULT_BASE_URL = "http://localhost:5174"
INSECURE_DEFAULT_DSN = "postgresql+asyncpg://kiosk:kiosk@postgres:5432/kkmi_kiosk"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Runtime
    env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    app_name: str = Field(default="kkmi-kiosk-backend")

    # Database
    database_url: str = Field(
        default=INSECURE_DEFAULT_DSN,
        description="SQLAlchemy async DSN for Postgres",
    )

    # Redis (revoke pub/sub + future cache)
    redis_url: str = Field(default="redis://redis:6379/0")

    # Auth
    jwt_secret: SecretStr = Field(default=SecretStr(INSECURE_DEFAULT_SECRET))
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_ttl_minutes: int = Field(default=15)
    jwt_refresh_ttl_days: int = Field(default=7)

    # Bootstrap super admin
    super_admin_email: str = Field(default="admin@example.com")
    super_admin_password: SecretStr = Field(default=SecretStr(INSECURE_DEFAULT_SECRET))

    # AI provider
    google_api_key: SecretStr = Field(default=SecretStr(""))

    # Voice backend selector. "gemini_live" (default) = native Gemini Live
    # audio. "kaa" = bridge the kiosk WS to the local Karakalpak STT→LLM→TTS
    # WebSocket server at KAA_WS_URL (kiosk protocol unchanged). Falls back to
    # gemini_live if "kaa" is selected but KAA_WS_URL is empty.
    voice_backend: str = Field(default="gemini_live")
    kaa_ws_url: str = Field(default="")

    # HEMIS — the institute's instance of the national higher-education system.
    # Read-only: the nightly sync mirrors schedules / groups / specialties into
    # our Postgres so the kiosk never waits on an upstream call mid-conversation.
    # The token is an admin-panel "API User" bearer token; backend-only, never
    # on a kiosk. Empty token → sync is skipped and the schedule menu serves
    # whatever was last mirrored.
    hemis_api_base: str = Field(default="https://student.kkmi.uz/rest")
    hemis_token: SecretStr = Field(default=SecretStr(""))
    hemis_timeout: int = Field(default=60)
    # Upstream allows 10 req/s. Stay under it — a nightly job has no reason to
    # race, and tripping their limiter costs far more time than it saves.
    hemis_rate_limit: float = Field(default=6.0)
    hemis_concurrency: int = Field(default=4)

    # Public base URL — used to build the QR verification URL embedded in
    # qabul receipts. Should match the gov-panel domain in production.
    public_base_url: str = Field(default=INSECURE_DEFAULT_BASE_URL)

    # Releases storage — where uploaded kiosk update bundles are written.
    releases_dir: Path = Field(default=Path("/var/lib/kiosk/releases"))

    # Officials photo storage — where uploaded hokim/orinbasar photos are
    # written. Served as static binaries from /api/public/officials/{id}/photo.jpg.
    # Mounted as a docker volume in prod so photos survive container rebuilds.
    photos_dir: Path = Field(default=Path("/var/lib/kiosk/photos"))

    # Scanned books + the page images rendered from them. A docker volume in
    # prod, same as releases and photos, so the scans survive a rebuild.
    books_dir: Path = Field(default=Path("/var/lib/kiosk/books"))

    # GitHub repo (owner/repo) to sync releases from. Empty disables sync.
    kiosk_github_repo: str = Field(default="")

    # Fine-grained PAT with Contents:Read on the kiosk repo. Required for
    # private repos (asset download is gated behind it). Empty = public repo
    # mode.
    github_token: SecretStr = Field(default=SecretStr(""))

    # Webhook HMAC secret. Must match the secret set in
    # GitHub → Settings → Webhooks for the kiosk repo.
    github_webhook_secret: SecretStr = Field(default=SecretStr(""))

    # When a webhook fires for a new release, mark it published immediately.
    # Default: false (super-admin reviews drafts in the panel).
    kiosk_auto_publish_on_github_sync: bool = Field(default=False)

    # Shared secret gating GET /health/deep. The status-page poller (Gatus)
    # sends it as the X-Health-Token header; public requests without it get
    # 401, so internal component states aren't exposed via the public api
    # vhost. Empty (dev) = endpoint is ungated.
    health_deep_token: SecretStr = Field(default=SecretStr(""))

    # CORS
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
        ]
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
