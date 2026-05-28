"""Kiosk-facing update channel endpoints.

GET /api/kiosk/updates/check
    Auth: signed-nonce (same as every other kiosk endpoint).
    Returns the latest published release in the kiosk's channel (currently
    always `stable`). The response includes everything the kiosk needs to
    decide whether to download: version, sha256, size, mandatory flag, URL.

GET /api/kiosk/updates/download/{release_id}
    Auth: signed-nonce. Streams the .nupkg bytes back. Kiosk verifies
    SHA-256 client-side before letting Velopack apply the update.

GET /api/kiosk/updates/manifest/{release_id}
    Auth: signed-nonce. Streams Velopack's `releases.{channel}.json` for the
    release, if present. Velopack's SimpleFileSource on the kiosk side needs
    this manifest in the same dir as the .nupkg to discover the update —
    without it `CheckForUpdatesAsync` returns null and no apply happens.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from ..core.config import get_settings
from ..core.deps import DbSession
from ..core.device_auth import AUTH_HEADER_NAME, resolve_device_from_signed_request
from ..core.errors import NotFoundError
from ..domain.release import CHANNEL_STABLE, STATUS_PUBLISHED, KioskRelease

router = APIRouter(prefix="/api/kiosk/updates", tags=["kiosk:updates"])


class UpdateCheckOut(BaseModel):
    available: bool
    version: str | None = None
    release_id: str | None = None
    file_sha256: str | None = None
    file_size: int | None = None
    file_name: str | None = None
    download_url: str | None = None
    # Velopack feed manifest (`releases.{channel}.json`). Present when the
    # backend has it on disk for this release. Kiosks that don't see this
    # field can fall back to legacy "download .nupkg only" behavior — but
    # apply will fail on Velopack's side without the manifest.
    manifest_url: str | None = None
    manifest_name: str | None = None
    mandatory: bool = False
    release_notes: str | None = None


@router.get("/check", response_model=UpdateCheckOut)
async def check_for_update(
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> UpdateCheckOut:
    # Authenticate the device. Revoked kiosks can't even check for updates —
    # they fail at the auth gate.
    await resolve_device_from_signed_request(session, x_kiosk_auth)

    latest = (
        await session.execute(
            select(KioskRelease)
            .where(
                KioskRelease.channel == CHANNEL_STABLE,
                KioskRelease.status == STATUS_PUBLISHED,
            )
            .order_by(KioskRelease.published_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        return UpdateCheckOut(available=False)

    settings = get_settings()
    # Manifest lives next to the .nupkg under the original Velopack filename
    # (e.g. releases.win.json — channel here is Velopack's OS channel, NOT
    # our DB release.channel "stable"/"rc"). _gh_pull_release writes whatever
    # filename the GH release ships; we glob for it.
    version_dir = settings.releases_dir / latest.version
    manifest_path = next(
        iter(sorted(version_dir.glob("releases.*.json"))),
        None,
    ) if version_dir.exists() else None
    manifest_url: str | None = None
    manifest_name: str | None = None
    if manifest_path is not None and manifest_path.exists():
        manifest_url = f"/api/kiosk/updates/manifest/{latest.id}"
        manifest_name = manifest_path.name

    return UpdateCheckOut(
        available=True,
        version=latest.version,
        release_id=str(latest.id),
        file_sha256=latest.file_sha256,
        file_size=latest.file_size,
        file_name=Path(latest.file_path).name,
        # Relative URL — kiosk joins with backend_url before fetching.
        download_url=f"/api/kiosk/updates/download/{latest.id}",
        manifest_url=manifest_url,
        manifest_name=manifest_name,
        mandatory=latest.mandatory,
        release_notes=latest.release_notes,
    )


@router.get("/download/{release_id}")
async def download_release(
    release_id: uuid.UUID,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> StreamingResponse:
    await resolve_device_from_signed_request(session, x_kiosk_auth)

    r = (
        await session.execute(
            select(KioskRelease).where(
                KioskRelease.id == release_id,
                KioskRelease.status == STATUS_PUBLISHED,
            )
        )
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError()

    settings = get_settings()
    file_path = settings.releases_dir / r.file_path
    if not file_path.exists():
        raise NotFoundError("release_file_missing")

    def _iter():
        with file_path.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(r.file_size),
            "Content-Disposition": f'attachment; filename="{Path(r.file_path).name}"',
            "X-Kiosk-Sha256": r.file_sha256,
        },
    )


@router.get("/manifest/{release_id}")
async def download_manifest(
    release_id: uuid.UUID,
    session: DbSession,
    x_kiosk_auth: str | None = Header(default=None, alias=AUTH_HEADER_NAME),
) -> StreamingResponse:
    await resolve_device_from_signed_request(session, x_kiosk_auth)

    r = (
        await session.execute(
            select(KioskRelease).where(
                KioskRelease.id == release_id,
                KioskRelease.status == STATUS_PUBLISHED,
            )
        )
    ).scalar_one_or_none()
    if r is None:
        raise NotFoundError()

    settings = get_settings()
    version_dir = settings.releases_dir / r.version
    manifest_path = next(
        iter(sorted(version_dir.glob("releases.*.json"))),
        None,
    ) if version_dir.exists() else None
    if manifest_path is None or not manifest_path.exists():
        raise NotFoundError("manifest_missing")

    def _iter():
        with manifest_path.open("rb") as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type="application/json",
        headers={
            "Content-Length": str(manifest_path.stat().st_size),
            "Content-Disposition": f'attachment; filename="{manifest_path.name}"',
        },
    )
