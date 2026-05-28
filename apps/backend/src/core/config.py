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
INSECURE_DEFAULT_DSN = "postgresql+asyncpg://kiosk:kiosk@postgres:5432/joqari_kenes"


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
    app_name: str = Field(default="joqari-kenes-backend")

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

    # Paths
    archive_dir: Path = Field(default=Path("/app/archive"))

    # Public base URL — used to build the QR verification URL embedded in
    # qabul receipts. Should match the gov-panel domain in production.
    public_base_url: str = Field(default=INSECURE_DEFAULT_BASE_URL)

    # Releases storage — where uploaded kiosk update bundles are written.
    releases_dir: Path = Field(default=Path("/var/lib/kiosk/releases"))

    # Officials photo storage — where uploaded hokim/orinbasar photos are
    # written. Served as static binaries from /api/public/officials/{id}/photo.jpg.
    # Mounted as a docker volume in prod so photos survive container rebuilds.
    photos_dir: Path = Field(default=Path("/var/lib/kiosk/photos"))

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

    # Telegram notification bot — posts every new murajaat and qabul to
    # two broadcast channels so the back-office staff see arrivals
    # without polling the gov-panel. All three fields are optional:
    # leaving the token empty disables the integration entirely (the
    # post helper is a no-op so dev / staging don't try to call
    # api.telegram.org). Channel IDs are the "-100XXXXXXXXXX" form
    # Telegram assigns to channels — obtainable by forwarding any
    # channel message to a chat-info bot.
    telegram_bot_token: SecretStr = Field(default=SecretStr(""))
    telegram_murajat_channel_id: str = Field(default="")
    telegram_qabul_channel_id: str = Field(default="")
    # Optional Cloudflare Worker relay — api.telegram.org is blocked
    # from the Moscow prod IP, so prod overrides this to a workers.dev
    # URL that forwards verbatim to api.telegram.org. Leave default to
    # call Telegram directly (dev / unblocked hosts). When the relay is
    # in use, `telegram_relay_token` must match the Worker's RELAY_TOKEN
    # secret or the Worker rejects 401.
    telegram_api_base: str = Field(default="https://api.telegram.org")
    telegram_relay_token: SecretStr = Field(default=SecretStr(""))

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
