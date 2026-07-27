"""Super-admin: kiosk binary release management.

Workflow:
  1. POST /upload — multipart form with the .exe / .nupkg file + version + channel.
     Server hashes (SHA-256), writes to releases_dir/{version}/{filename},
     inserts a `draft` row.
  2. POST /sync-github — pull the latest asset from a configured GitHub
     repo's releases. Inserts as `draft` with source=github.
  3. GET / — list with filter dropdowns.
  4. POST /{id}/publish — flips draft|unpublished → published. From this
     moment kiosks see it on /api/kiosk/updates/check.
  5. POST /{id}/unpublish — emergency rollback.
  6. DELETE /{id} — only allowed for non-published rows.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog
from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from ...core import audit
from ...core.config import get_settings
from ...core.deps import DbSession, SuperAdmin
from ...core.errors import (
    AppError,
    AuthError,
    NotFoundError,
    ServiceUnavailableError,
    UpstreamError,
    ValidationError,
)
from ...core.redis_bus import RELEASE_PUBLISHED_CHANNEL, bus
from ...domain.release import (
    ALL_CHANNELS,
    CHANNEL_STABLE,
    SOURCE_GITHUB,
    SOURCE_MANUAL,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    STATUS_UNPUBLISHED,
    KioskRelease,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/super/releases", tags=["super:releases"])

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


class ReleaseOut(BaseModel):
    id: str
    version: str
    channel: str
    status: str
    file_name: str
    file_sha256: str
    file_size: int
    release_notes: str
    mandatory: bool
    published_at: str | None
    source: str
    github_release_id: str | None
    created_at: str
    updated_at: str


class ReleaseListOut(BaseModel):
    items: list[ReleaseOut]
    total: int


def _to_out(r: KioskRelease) -> ReleaseOut:
    return ReleaseOut(
        id=str(r.id),
        version=r.version,
        channel=r.channel,
        status=r.status,
        file_name=Path(r.file_path).name,
        file_sha256=r.file_sha256,
        file_size=r.file_size,
        release_notes=r.release_notes,
        mandatory=r.mandatory,
        published_at=r.published_at.isoformat() if r.published_at else None,
        source=r.source,
        github_release_id=r.github_release_id,
        created_at=r.created_at.isoformat(),
        updated_at=r.updated_at.isoformat(),
    )


@router.get("", response_model=ReleaseListOut)
async def list_releases(
    session: DbSession,
    _: SuperAdmin,
    channel: str | None = None,
    status: str | None = None,
) -> ReleaseListOut:
    stmt = select(KioskRelease).order_by(KioskRelease.created_at.desc())
    if channel:
        stmt = stmt.where(KioskRelease.channel == channel)
    if status:
        stmt = stmt.where(KioskRelease.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return ReleaseListOut(items=[_to_out(r) for r in rows], total=len(rows))


class UploadOut(BaseModel):
    release: ReleaseOut


@router.post("/upload", response_model=UploadOut)
async def upload_release(
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
    file: UploadFile = File(...),
    version: str = Form(...),
    channel: str = Form(default=CHANNEL_STABLE),
    release_notes: str = Form(default=""),
    mandatory: bool = Form(default=False),
) -> UploadOut:
    if not VERSION_RE.match(version):
        raise ValidationError("invalid_version_format")
    if channel not in ALL_CHANNELS:
        raise ValidationError("invalid_channel")
    if not file.filename:
        raise ValidationError("missing_filename")

    settings = get_settings()
    target_dir = settings.releases_dir / version
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]", "_", file.filename)
    target_path = target_dir / safe_name

    h = hashlib.sha256()
    size = 0
    with target_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
            h.update(chunk)
            size += len(chunk)

    rel = KioskRelease(
        version=version,
        channel=channel,
        status=STATUS_DRAFT,
        file_path=str(target_path.relative_to(settings.releases_dir)),
        file_sha256=h.hexdigest(),
        file_size=size,
        release_notes=release_notes,
        mandatory=mandatory,
        source=SOURCE_MANUAL,
        uploaded_by=actor.id,
    )
    session.add(rel)
    await session.flush()

    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="release.upload",
        entity_type="kiosk_release",
        entity_id=rel.id,
        request=request,
        after={"version": version, "channel": channel, "size": size},
    )
    return UploadOut(release=_to_out(rel))


@router.post("/{release_id}/publish", response_model=ReleaseOut)
async def publish_release(
    release_id: uuid.UUID,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> ReleaseOut:
    r = (
        await session.execute(select(KioskRelease).where(KioskRelease.id == release_id))
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError()
    if r.status == STATUS_PUBLISHED:
        return _to_out(r)
    r.status = STATUS_PUBLISHED
    r.published_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="release.publish",
        entity_type="kiosk_release",
        entity_id=r.id,
        request=request,
        after={"version": r.version, "channel": r.channel},
    )
    # Notify any active kiosks via Redis so they can prompt to update without
    # waiting for their next startup. Kiosk subscribes via WS recheck task —
    # for now this is informational.
    await bus.publish(RELEASE_PUBLISHED_CHANNEL, str(r.id))
    return _to_out(r)


@router.post("/{release_id}/unpublish", response_model=ReleaseOut)
async def unpublish_release(
    release_id: uuid.UUID,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> ReleaseOut:
    r = (
        await session.execute(select(KioskRelease).where(KioskRelease.id == release_id))
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError()
    if r.status != STATUS_PUBLISHED:
        return _to_out(r)
    r.status = STATUS_UNPUBLISHED
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="release.unpublish",
        entity_type="kiosk_release",
        entity_id=r.id,
        request=request,
    )
    return _to_out(r)


@router.delete("/{release_id}", status_code=204)
async def delete_release(
    release_id: uuid.UUID,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> None:
    r = (
        await session.execute(select(KioskRelease).where(KioskRelease.id == release_id))
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError()
    if r.status == STATUS_PUBLISHED:
        raise ValidationError("cannot_delete_published_release")

    settings = get_settings()
    file_full = settings.releases_dir / r.file_path
    try:
        if file_full.exists():
            file_full.unlink()
    except OSError as e:
        logger.warning("release_file_delete_failed", path=str(file_full), error=str(e))

    await session.delete(r)
    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="release.delete",
        entity_type="kiosk_release",
        entity_id=r.id,
        request=request,
    )


# ── GitHub Releases sync ────────────────────────────────────────────────


class SyncIn(BaseModel):
    """Body for the /sync-github endpoint. asset_filter matches .nupkg only —
    that is the Velopack package format the kiosk's SimpleFileSource feeds
    from. Setup.exe is the first-time installer (operator downloads it from
    the GH Release page directly), .zip is unused."""
    channel: str = Field(default=CHANNEL_STABLE)
    asset_filter: str = Field(default=r"\.nupkg$")
    """Regex matched against asset filenames; first match wins."""

    @field_validator("channel")
    @classmethod
    def channel_known(cls, v: str) -> str:
        if v not in ALL_CHANNELS:
            raise ValueError("invalid channel")
        return v


class SyncOut(BaseModel):
    pulled: ReleaseOut | None
    skipped_reason: str | None


def _gh_headers() -> dict[str, str]:
    """Build GitHub API headers. PAT is included for private repos so asset
    download (which redirects to a presigned codeload URL) is authorized."""
    settings = get_settings()
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "kkmi-kiosk-backend",
    }
    token = settings.github_token.get_secret_value().strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _gh_pull_release(
    session,
    *,
    repo: str,
    release_data: dict | None = None,
    asset_pattern: str = r"\.nupkg$",
    channel: str = CHANNEL_STABLE,
    actor_user_id: uuid.UUID | None = None,
) -> KioskRelease | str:
    """Core sync logic. Pulls one GitHub release into kiosk_releases.

    `release_data` may be passed by the webhook handler (saving the API call);
    otherwise we fetch latest from GitHub. Returns either the inserted row,
    or a string `skipped_reason`.
    """
    settings = get_settings()
    headers = _gh_headers()

    if release_data is None:
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        async with httpx.AsyncClient(timeout=30, headers=headers) as http:
            resp = await http.get(api_url)
        if resp.status_code != 200:
            raise UpstreamError(f"github_api_status_{resp.status_code}")
        release_data = resp.json()

    version = (release_data.get("tag_name") or "").lstrip("v").strip()
    gh_id = str(release_data.get("id") or "")
    if not VERSION_RE.match(version) or not gh_id:
        raise ValidationError("github_release_missing_fields")

    # Skip if already imported.
    existing = (
        await session.execute(
            select(KioskRelease).where(KioskRelease.github_release_id == gh_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return "already_imported"

    # asset_pattern defaults to `\.nupkg$` — that's the Velopack package
    # format the kiosk's SimpleFileSource needs. Setup.exe is the first-time
    # installer and not valid for the update feed.
    asset_re = re.compile(asset_pattern)
    asset = next(
        (a for a in (release_data.get("assets") or []) if asset_re.search(a.get("name", ""))),
        None,
    )
    if asset is None:
        raise ValidationError("github_no_matching_asset")

    name = asset.get("name", f"kiosk-{version}.bin")
    asset_id = asset.get("id")
    # For private repos, hitting `browser_download_url` would 404 unless we
    # pass the API auth header AND `Accept: application/octet-stream`. Easier:
    # always go through the API endpoint /repos/.../releases/assets/{id} —
    # that one accepts our Bearer token for both public and private repos.
    asset_dl_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
    dl_headers = dict(headers)
    dl_headers["Accept"] = "application/octet-stream"

    target_dir = settings.releases_dir / version
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]", "_", name)
    target_path = target_dir / safe_name

    h = hashlib.sha256()
    size = 0
    async with httpx.AsyncClient(
        timeout=600, follow_redirects=True, headers=dl_headers
    ) as http:
        async with http.stream("GET", asset_dl_url) as r:
            r.raise_for_status()
            with target_path.open("wb") as out:
                async for chunk in r.aiter_bytes(1024 * 1024):
                    out.write(chunk)
                    h.update(chunk)
                    size += len(chunk)

    # Velopack feed manifest. `vpk pack` emits a `releases.{velopack_channel}.json`
    # alongside the .nupkg — without it, Velopack's SimpleFileSource on the
    # kiosk side returns null and the update loop never converges. The
    # velopack_channel ("win" for Windows kiosks) is independent of our DB
    # release.channel ("stable"/"rc"/"dev"), so we store the file under its
    # original filename and let the /check endpoint pick it up via glob.
    # Missing manifest is non-fatal — falls back to no-op (kiosk skips apply).
    manifest_re = re.compile(r"^releases\..+\.json$", re.IGNORECASE)
    manifest_asset = next(
        (a for a in (release_data.get("assets") or [])
         if manifest_re.search(a.get("name", ""))),
        None,
    )
    if manifest_asset is not None:
        m_url = f"https://api.github.com/repos/{repo}/releases/assets/{manifest_asset['id']}"
        m_name = re.sub(r"[^\w.\-]", "_", manifest_asset["name"])
        m_path = target_dir / m_name
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=True, headers=dl_headers
        ) as http:
            mr = await http.get(m_url)
            if mr.status_code == 200:
                m_path.write_bytes(mr.content)

    auto_publish = settings.kiosk_auto_publish_on_github_sync
    rel = KioskRelease(
        version=version,
        channel=channel,
        status=STATUS_PUBLISHED if auto_publish else STATUS_DRAFT,
        published_at=datetime.now(UTC) if auto_publish else None,
        file_path=str(target_path.relative_to(settings.releases_dir)),
        file_sha256=h.hexdigest(),
        file_size=size,
        release_notes=(release_data.get("body") or "")[:4000],
        mandatory=False,
        source=SOURCE_GITHUB,
        github_release_id=gh_id,
        uploaded_by=actor_user_id,
    )
    session.add(rel)
    await session.flush()
    if auto_publish:
        await bus.publish(RELEASE_PUBLISHED_CHANNEL, str(rel.id))
    return rel


@router.post("/sync-github", response_model=SyncOut)
async def sync_from_github(
    payload: SyncIn,
    session: DbSession,
    actor: SuperAdmin,
    request: Request,
) -> SyncOut:
    settings = get_settings()
    repo = settings.kiosk_github_repo.strip()
    if not repo or "/" not in repo:
        raise ServiceUnavailableError("github_repo_not_configured")

    result = await _gh_pull_release(
        session,
        repo=repo,
        asset_pattern=payload.asset_filter,
        channel=payload.channel,
        actor_user_id=actor.id,
    )
    if isinstance(result, str):
        return SyncOut(pulled=None, skipped_reason=result)

    await audit.record(
        session,
        actor_user_id=actor.id,
        actor_org_id=None,
        action="release.github_sync",
        entity_type="kiosk_release",
        entity_id=result.id,
        request=request,
        after={"version": result.version, "github_id": result.github_release_id},
    )
    return SyncOut(pulled=_to_out(result), skipped_reason=None)


# ── GitHub webhook (auto-sync on `release` events) ──────────────────────


@router.post("/github-webhook", status_code=204)
async def github_release_webhook(
    request: Request,
    session: DbSession,
) -> None:
    """Receive `release` event from GitHub. Configured at:
        repo → Settings → Webhooks → Add webhook
        URL:    https://kiosk-api.<domain>/api/super/releases/github-webhook
        Secret: KIOSK env GITHUB_WEBHOOK_SECRET
        Events: only "Releases"

    HMAC-SHA256 verification rejects forged payloads. We only act on
    action='published' to avoid noise from drafts/edits.
    """
    settings = get_settings()
    secret = settings.github_webhook_secret.get_secret_value().encode()
    if not secret:
        raise ServiceUnavailableError("webhook_not_configured")

    body = await request.body()
    sig_header = request.headers.get("x-hub-signature-256", "")
    if not sig_header.startswith("sha256="):
        raise AuthError("webhook_signature_missing")

    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig_header):
        raise AuthError("webhook_signature_invalid")

    event = request.headers.get("x-github-event", "")
    if event != "release":
        return  # ignore ping, etc.

    payload = json.loads(body)
    if payload.get("action") != "published":
        return  # only act on actual publish, not edits/drafts

    repo_full = payload.get("repository", {}).get("full_name", "")
    if not repo_full or "/" not in repo_full:
        raise ValidationError("webhook_repo_missing")
    if (
        settings.kiosk_github_repo
        and repo_full.lower() != settings.kiosk_github_repo.lower()
    ):
        # Stray webhook from a different repo — silently ignore rather than
        # surfacing details.
        return

    release_data = payload.get("release") or {}
    try:
        result = await _gh_pull_release(
            session,
            repo=repo_full,
            release_data=release_data,
            asset_pattern=r"\.nupkg$",
            channel=CHANNEL_STABLE,
            actor_user_id=None,
        )
    except AppError:
        # Re-raise so the response is a real error code (GitHub will retry).
        raise
    except Exception as e:
        logger.exception("github_webhook_pull_failed")
        raise UpstreamError("github_pull_failed", cause=e) from e

    if isinstance(result, str):
        logger.info("github_webhook_skipped", reason=result)
        return

    logger.info(
        "github_webhook_pulled",
        version=result.version,
        gh_id=result.github_release_id,
        auto_published=settings.kiosk_auto_publish_on_github_sync,
    )
    await audit.record(
        session,
        actor_user_id=None,
        actor_org_id=None,
        action="release.github_webhook",
        entity_type="kiosk_release",
        entity_id=result.id,
        request=request,
        after={
            "version": result.version,
            "github_id": result.github_release_id,
            "auto_published": settings.kiosk_auto_publish_on_github_sync,
        },
    )
