# Backend production image — single-stage. The earlier multi-stage approach
# tried to pre-build wheels with hatchling (PEP 517 build backend), but that
# requires hatchling itself to be wheel'd alongside, and it's easier to just
# install once with build tools present and live with a slightly larger image.
# Final size ~250 MB.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps for asyncpg, argon2-cffi, etc., plus libpq5 + ca-certs at runtime.
# build-essential / libpq-dev are kept in the final image because compiled
# wheels of native deps may not exist for python:3.12-slim's combo and we'd
# rather have a working image than chase --only-binary all the way.
#
# fonts-dejavu (full set: Regular + Bold + Oblique) for Cyrillic-safe
# receipt rendering. fonts-dejavu-core ships only Regular + Bold —
# the Oblique face (italic position descriptor on the receipt) needs
# the full package. See src/ai/receipt.py.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev libpq5 ca-certificates curl \
        fonts-dejavu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --no-create-home app

# INSTALL_DEV=1 adds pytest/ruff/mypy. Only docker-compose.dev.yml sets it —
# the production image stays lean. Without this `make test` had nothing to run:
# the image installed the runtime extras only, so `exec backend pytest` failed
# with "executable file not found".
ARG INSTALL_DEV=0

COPY pyproject.toml /app/
RUN pip install --upgrade pip \
 && if [ "$INSTALL_DEV" = "1" ]; then pip install -e ".[dev]"; else pip install -e .; fi

COPY alembic.ini /app/
COPY alembic /app/alembic
COPY src /app/src

# Volume mount targets. `app` user owns them so /api/super/releases/upload
# and /api/gov/officials/<id>/photo writes succeed even when the volume is
# created fresh (docker volumes default to root-owned mountpoints).
RUN mkdir -p /var/lib/kiosk/releases /var/lib/kiosk/photos \
 && chown -R app:app /var/lib/kiosk /app
USER app

EXPOSE 8000

# Run migrations on every container start. Idempotent. If a migration fails
# the container exits non-zero and the deploy fails fast.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 2"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
