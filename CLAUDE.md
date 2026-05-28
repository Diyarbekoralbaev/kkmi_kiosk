# CLAUDE.md

Guidance for Claude Code working on this branch (`rebuild/v2`).

## Project at a glance

Multi-tenant SaaS for the Karakalpakstan Hokimiyat AI voice kiosk. One you (super admin) serves multiple gov customers. Each gov has their own panel for managing murajaatlar (applications) and AI config.

**This branch is a from-scratch rebuild.** The pre-rebuild code lives in `archive/` for reference and one-time data migration. Do not import from `archive/` in new code; the only allowed touch is `archive/old_config/ai-agent.yaml` read by the seed module.

## Layout

```
apps/
  backend/          FastAPI + SQLAlchemy 2 async + Alembic + google-genai
  super-panel/      React 19 SPA — your provider admin (port 5173)
  gov-panel/        React 19 SPA — gov customer admin (port 5174)
deploy/
  docker-compose.dev.yml
archive/            old AVA / kiosk_ui / SQLite (reference only)
docs/
  ARCHITECTURE.md, API.md
```

## Common commands

```bash
make up        # docker compose up (postgres + backend + 2 panels)
make migrate   # alembic upgrade head
make test      # pytest
make lint      # ruff
make psql      # psql shell into dev postgres
make logs      # tail backend logs
```

## Architectural rules

- **Tenancy is enforced via `core/deps.current_org`**. Gov endpoints must depend on `OrgAdmin` and `CurrentOrg`. Never trust `org_id` from request body.
- **Errors are opaque**. Raise `AppError` subclasses with codes; never return raw exception messages to clients. The wrapper logs the real exception with a `correlation_id`.
- **All write endpoints must call `core/audit.record(...)`**. Reads are not audited.
- **No YAML for AI config**. The agent prompt is built from DB rows in `prompt_builder.py`. Editing the config is via API endpoints, never via files.
- **One AI provider, one SDK**. Gemini Live via `google-genai`. Don't reintroduce raw WebSocket plumbing or Asterisk telephony code (that's all in `archive/old_src/`).
- **Two SPAs, not one**. Code duplication between `super-panel/` and `gov-panel/` is intentional — security boundary.

## Auth

- Super admin: MFA required (TOTP). Bootstrap from `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` env vars.
- Gov admin: MFA optional.
- Argon2id passwords. JWT access (15 min) + refresh (7 days, rotated, hashed in DB).

## Out of scope (next plans)

- C# Avalonia kiosk client (TPM-bound mTLS, signed binary, auto-update)
- Production deploy (Caddy + Let's Encrypt)
- Backups, observability, CI/CD, email, real-time notifications

## When in doubt

- New endpoint? Place in `apps/backend/src/api/super/...` or `apps/backend/src/api/gov/...` and depend on `SuperAdmin` or `OrgAdmin` + `CurrentOrg`.
- New table? Add a model under `apps/backend/src/domain/`, register in `domain/__init__.py`, write an Alembic migration.
- New error case? Subclass `AppError` with a fresh code in `core/errors.py`.
- New AI prompt section? Extend `SECTION_KEYS` in `domain/ai_config.py` and seed it in `core/seed.py`.
