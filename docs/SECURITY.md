# Security

This document tracks the threat model, what's protected today, what's deferred, and the operator responsibilities.

## Protected today

- **Tenant isolation**: every gov endpoint filters by `current_org.id` at the SQL level. Direct row access is impossible cross-org. Verified manually for all gov endpoints in `apps/backend/src/api/gov/`.
- **Locked AI prompt sections never leave the server.** `/api/gov/settings/ai` filters `gov_editable=True` at the query. Identity, tool_rules, and any other locked sections are not in the API response — DevTools won't reveal them. `update_section` also enforces `gov_editable` server-side.
- **Passwords**: Argon2id (passlib). Plain passwords appear only on creation/reset, returned to the actor exactly once, never logged.
- **JWT**: HS256 with secret from env. Access token TTL 15 min. Refresh token TTL 7 days, **rotated** on every use, JTI hashed in DB so revocation is server-side.
- **MFA**: TOTP. Required for `super_admin`; optional for `org_admin`.
- **Opaque error codes**: clients only ever see `{ code, message, correlation_id }`. Real exceptions go to structlog under the same correlation id. No stack traces, no SQL details, no Gemini quota messages reach the wire.
- **Audit log**: every panel write action is recorded (org/user CRUD, password resets, application status changes, AI section/screen/officials edits, MFA enable/disable, login success, login failure, logout, password change, device revoke). Used by super admin for forensics and brute-force detection.
- **CORS**: explicit origin list (no `*`). Default: `localhost:5173` and `localhost:5174`.
- **Static analysis baseline**: `python -m py_compile` on every backend file is part of pre-commit; `ruff` configured.
- **Insecure-defaults check**: backend refuses to start in `ENV=production` if `JWT_SECRET` or `SUPER_ADMIN_PASSWORD` is still the `change-me-please` placeholder. In dev a loud warning is logged.
- **API documentation**: `/docs`, `/redoc`, `/openapi.json` are **disabled** when `ENV=production`.
- **Postgres dev port**: bound to `127.0.0.1:5433` only. Never exposed externally.

## Known deferred risks (test stage)

These are accepted for the current test/v1 stage. Each has an owner-action note for when production is targeted.

| Area | Risk | Mitigation today | Action before prod |
|---|---|---|---|
| **Kiosk WebSocket** (`/ws/kiosk/voice`) | Public — anyone can open a Gemini session (cost) and spam applications | None | mTLS with TPM-bound client cert (next plan). At minimum, IP rate limit + enrollment-token gate as a stopgap. |
| **Rate limiting** | None on any endpoint. Brute-force login is bounded only by Argon2 cost | Audit log captures attempts | Add `slowapi` or Caddy-level rate limiting before exposing publicly |
| **HTTPS / reverse proxy** | Backend serves plain HTTP | localhost dev only | Caddy + Let's Encrypt + HSTS |
| **Postgres credentials** | `kiosk:kiosk` for dev | localhost-only bind | Strong unique password from secrets manager; never commit |
| **Backups** | None | — | pgBackRest / pg_dump cron + off-site (B2/R2) |
| **Secrets at rest** | `.env` on host filesystem, mode 600 | — | Vault / AWS Secrets Manager / Doppler |
| **Logout** | Revokes refresh token; access token (15 min TTL) cannot be invalidated mid-session | Short TTL bounds window | Optional access-token denylist in Redis if 15 min is too long |
| **Failed-login throttle** | Audit only, no auto-lock | — | After N failures within a window, lock for M minutes (DB-stored counter or fail2ban-style) |
| **Email delivery for password reset / MFA recovery** | None | Super admin manually communicates temp passwords | SMTP / Resend / SES |
| **Frontend XSS surface** | Tokens in `localStorage` (XSS would extract) | No `console.log`, dependencies audited | CSP header, dependency scanner in CI |

## Operator responsibilities

When running this in any non-localhost environment, the operator MUST:

1. Set `ENV=production` so the auto-disable of `/docs` kicks in and the insecure-defaults check raises.
2. Generate `JWT_SECRET` with `openssl rand -hex 32` and put in `.env`.
3. Generate a unique `SUPER_ADMIN_PASSWORD` with at least 16 random characters.
4. Place a reverse proxy (Caddy is what we recommend) terminating TLS in front of the backend.
5. Restrict Postgres host port to localhost or a private network — never `0.0.0.0`.
6. Rotate `org_credentials` if they leak; super admin can do this from the panel.
7. Monitor `audit.user.login.failed` — sustained failures from one IP usually mean credential stuffing.

## Reporting

Internal — please file under [security] in your project tracker. Critical issues (auth bypass, data leak across tenants, secret exposure) take priority over feature work.
