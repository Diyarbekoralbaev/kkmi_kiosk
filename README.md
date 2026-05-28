# Kiosk Gov

Multi-tenant SaaS backend + super-admin/gov-admin React panels for the Karakalpakstan Hokimiyat AI voice kiosk.

This branch (`rebuild/v2`) is a from-scratch rebuild. The old code lives in `archive/` for reference.

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 async, asyncpg, Alembic, Pydantic v2 |
| Auth | Argon2id passwords, JWT (access + refresh rotation), TOTP MFA |
| AI | Gemini Live (`google-genai` SDK), Charon voice |
| Database | Postgres 16 |
| Frontend | React 19 + Vite + TS + Tailwind + TanStack Query, two SPAs |
| Reverse proxy (prod) | Caddy (auto-HTTPS) |
| Kiosk client | C# Avalonia 11 (next plan, not in this branch) |

## Layout

```
apps/
  backend/         FastAPI service + Alembic
  super-panel/     React SPA — your (provider) admin
  gov-panel/       React SPA — gov customer admin
deploy/
  docker-compose.dev.yml
archive/           old AVA / kiosk_ui / SQLite — reference only
```

## Running locally

1. `cp .env.example .env` and fill in `GOOGLE_API_KEY`, set strong `JWT_SECRET` and `SUPER_ADMIN_PASSWORD`.
2. `make up` — starts Postgres, backend, super-panel (5173), gov-panel (5174).
3. The first run automatically:
   - Applies all Alembic migrations
   - Seeds `system_ai_defaults` from `archive/old_config/ai-agent.yaml`
   - Creates the default `Nukus Hokimiyatı` org with cloned defaults + 6 KB officials
   - Creates the super admin user from `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`
4. Open `http://localhost:5173` (super) and `http://localhost:5174` (gov).

## Tasks (slices done)

- [x] Slice 1: Repo cleanup
- [x] Slice 2: Backend foundation
- [x] Slice 3: Auth + MFA
- [x] Slice 4: Super admin API + SPA
- [x] Slice 5: Gov admin API + SPA
- [x] Slice 6: AI config schema + seed
- [x] Slice 7: AI config API + UI
- [x] Slice 8: AI engine rewrite
- [x] Slice 9: Kiosk WS endpoint
- [x] Slice 10: Audit log
- [x] Slice 11: Polish + verification

## Out of scope (future)

- C# Avalonia kiosk client + TPM-bound mTLS (next plan)
- Caddy production deployment, Let's Encrypt
- Backups (pgBackRest), observability (Prometheus/Grafana/Sentry), CI/CD
- Email infra (password reset / MFA recovery)
- Real-time WS notifications to gov panel
