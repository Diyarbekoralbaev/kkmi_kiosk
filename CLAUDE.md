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

# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
