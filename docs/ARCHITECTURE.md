# Architecture

## Tenancy model

- **Organization** = one Hokimiyat customer (Nukus, Toshkent, ...).
- **User** = panel login. `role ∈ {super_admin, org_admin}`.
  - `super_admin.org_id` is NULL.
  - `org_admin.org_id` is required.
- **Org credentials** = single username/password per org, used at kiosk first-run enrollment (data model lives here, endpoint lands in the next plan).
- **Device** = one physical kiosk, bound to an org. Schema lands here; the enrollment endpoint comes next.

All tenant-scoped data tables (`applications`, `voice_sessions`, `devices`, `org_*`) carry `org_id` and are filtered through `core/deps.current_org` for gov endpoints. Super-admin endpoints are not tenant-scoped.

## Auth flow

1. `POST /api/auth/login` with email + password
   - Super admin with TOTP enabled → 200 `{ mfa_required: true, mfa_session_token }`
   - Else → 200 `{ access_token, refresh_token, user }`
2. `POST /api/auth/mfa/verify` with `{ mfa_session_token, code }` → tokens.
3. Access token → 15 min. Refresh → 7 days, **rotated** on every refresh.
4. Refresh token JTI stored hashed in `refresh_tokens` (revocable).

## Error handling

`core/errors.py` defines an `AppError` hierarchy with **opaque codes** like `E_AUTH_002`. Clients only ever see `{ code, message, correlation_id }`. The real exception (with stack) is logged via structlog under the same correlation id.

| Code | Meaning |
|---|---|
| `E_AUTH_00x` | Auth failures |
| `E_PERM_001` | Permission denied |
| `E_VAL_00x` | Validation / not found / conflict |
| `E_RATE_001` | Rate limit |
| `E_DB_001` | Database error |
| `E_PRV_001` | AI provider (Gemini Live) error |
| `E_INT_999` | Unhandled internal |

## AI agent config (DB-driven)

| Table | Purpose |
|---|---|
| `system_ai_defaults` | Singleton row. Cloned into every new org. Owns: model, voice, tuning, default_sections (JSONB), default_screens, default_tools, default_officials. |
| `org_ai_settings` | Per-org tuning (model, voice, temperature, ...). |
| `org_prompt_sections` | Per-org system prompt fragments (`greeting`, `identity`, `tool_rules`, `screen_*`, `speaking_style`, `scope`, `fallback`). Each has a `gov_editable` flag. |
| `org_screens` | Which UI screens are enabled (`home`, `reception`, `submit`, `contacts`). |
| `org_tools` | Which tool calls are enabled (`navigate_to_screen`, `preview_application`, `submit_application`). |
| `org_kb_officials` | Hokim / orinbasar list with reception day+time. |

The kiosk WS handler builds the final system prompt at session start by reading these tables in order — no YAML, no file I/O.

## Kiosk WS lifecycle

1. Kiosk connects to `WS /ws/kiosk/voice` (public for now, mTLS in next plan).
2. Backend resolves the default org (only Nukus until kiosk plan adds device→org binding).
3. `prompt_builder.load_agent_config(org_id)` → `AgentConfig` (system_prompt + tuning + tools + screens).
4. `GeminiLiveSession(config).start()` opens a bidi stream with Gemini Live.
5. Kiosk → backend: 16 kHz PCM mono Int16 LE binary frames + JSON control (`screen_context`).
6. Backend → kiosk: 24 kHz PCM Int16 LE audio + JSON events (`navigate`, `application_preview`, `application_submitted`, `transcript`, `audio_done`, `error`, `disconnected`).
7. Tool calls from Gemini: dispatched to `_dispatch_tool` which:
   - `navigate_to_screen` → forwards to UI
   - `preview_application` → caches preview, forwards to UI
   - `submit_application` → INSERT into `applications`, forwards to UI
   Each tool gets a `send_tool_response` back to Gemini.
8. On disconnect: `voice_sessions` row is finalised with transcript, duration, error_code.

## Audit log

Every write endpoint calls `core/audit.record(...)` with actor, action, entity, before/after JSONB, IP, UA. Read via `GET /api/super/audit` with filters.

## Container topology

Single dev container per role:

```
postgres:16 ──┬── backend  (FastAPI + uvicorn --reload)
              ├── super-panel (vite dev, :5173)
              └── gov-panel   (vite dev, :5174)
```

Production additions (next plan): Caddy reverse proxy with auto-HTTPS + mTLS for kiosk WS.

## Out of this plan

- C# Avalonia kiosk client (next plan: TPM-bound mTLS, signed installer, auto-update)
- Caddy production deploy + Let's Encrypt
- Backups, observability, CI/CD
- Email infra
- Real-time push notifications
- File attachments to applications
