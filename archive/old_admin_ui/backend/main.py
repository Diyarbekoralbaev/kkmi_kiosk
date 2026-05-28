from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
import os
import logging
import secrets

import settings

load_dotenv(settings.ENV_PATH)

# SECURITY: If JWT_SECRET is missing when binding remotely, generate an ephemeral one
_uvicorn_host = os.getenv("UVICORN_HOST", "0.0.0.0")
_is_remote_bind = _uvicorn_host not in ("127.0.0.1", "localhost", "::1")
_placeholder_secrets = {"", "change-me-please", "changeme"}
_raw_jwt_secret = (os.getenv("JWT_SECRET", "") or "").strip()

if _is_remote_bind and _raw_jwt_secret in _placeholder_secrets:
    os.environ["JWT_SECRET"] = secrets.token_hex(32)
    logging.getLogger(__name__).warning(
        "JWT_SECRET missing/placeholder while bound to %s. Generated ephemeral secret. "
        "Set a strong JWT_SECRET in .env for production.",
        _uvicorn_host,
    )

from api import config, system, logs, mcp, tools, kiosk_voice, sessions  # noqa: E402
import auth  # noqa: E402

_enable_api_docs = os.getenv("ENABLE_API_DOCS", "true").lower() in ("1", "true", "yes")

app = FastAPI(
    title="Kiosk Gov Admin API",
    description="REST API for managing the Kiosk Gov voice agent.",
    version="1.0.0",
    docs_url="/docs" if _enable_api_docs else None,
    redoc_url="/redoc" if _enable_api_docs else None,
    openapi_url="/openapi.json" if _enable_api_docs else None,
    openapi_tags=[
        {"name": "auth", "description": "Authentication"},
        {"name": "config", "description": "YAML configuration editor"},
        {"name": "system", "description": "System/container health"},
        {"name": "sessions", "description": "Kiosk sessions and transcripts"},
        {"name": "logs", "description": "Container logs"},
        {"name": "tools", "description": "Tool catalog and tests"},
        {"name": "mcp", "description": "MCP server status"},
    ],
)

auth.load_users()

if getattr(auth, "USING_PLACEHOLDER_SECRET", False):
    logging.getLogger(__name__).warning(
        "JWT_SECRET is missing/placeholder; Admin UI is using an insecure secret."
    )


def _parse_cors_origins() -> list[str]:
    raw = (settings.get_setting("ADMIN_UI_CORS_ORIGINS", "") or "").strip()
    if not raw:
        return ["http://localhost:3003", "http://127.0.0.1:3003"]
    if raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


cors_origins = _parse_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials="*" not in cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Public routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])

# Kiosk voice WebSocket (no auth — public kiosk endpoint)
app.include_router(kiosk_voice.router)

# Protected routes
_protected = [Depends(auth.get_current_user)]
app.include_router(config.router, prefix="/api/config", tags=["config"], dependencies=_protected)
app.include_router(system.router, prefix="/api/system", tags=["system"], dependencies=_protected)
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"], dependencies=_protected)
app.include_router(logs.router, prefix="/api/logs", tags=["logs"], dependencies=_protected)
app.include_router(mcp.router, dependencies=_protected)
app.include_router(tools.router, prefix="/api/tools", tags=["tools"], dependencies=_protected)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Serve static frontend (production/docker)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    static_files = StaticFiles(directory=static_dir, html=False)
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")
    index_file = os.path.join(static_dir, "index.html")

    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not found")
        if full_path:
            resolved_path, stat_result = static_files.lookup_path(full_path.lstrip("/"))
            if stat_result and os.path.isfile(resolved_path):
                return FileResponse(resolved_path)
        response = FileResponse(index_file)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3003, reload=True)
