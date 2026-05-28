# API quick reference

All endpoints return `{ code, message, correlation_id }` on errors. Authenticate via `Authorization: Bearer <access_token>` header.

## Public

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness + DB ping |
| POST | `/api/auth/login` | Body: `{ email, password }` |
| POST | `/api/auth/mfa/verify` | Body: `{ mfa_session_token, code }` |
| POST | `/api/auth/refresh` | Body: `{ refresh_token }` |
| WS | `/ws/kiosk/voice` | Binary PCM up + binary PCM down + JSON control |

## Authenticated (any role)

| Method | Path |
|---|---|
| GET | `/api/auth/me` |
| POST | `/api/auth/logout` |
| POST | `/api/auth/mfa/setup` |
| POST | `/api/auth/mfa/enable` |
| POST | `/api/auth/mfa/disable` |
| POST | `/api/auth/password/change` |

## Super admin

| Method | Path |
|---|---|
| GET | `/api/super/orgs` |
| POST | `/api/super/orgs` (returns plain creds **once**) |
| GET | `/api/super/orgs/{id}` |
| PATCH | `/api/super/orgs/{id}` |
| POST | `/api/super/orgs/{id}/credentials/regenerate` |
| GET | `/api/super/users` |
| POST | `/api/super/users` (returns temp_password **once**) |
| PATCH | `/api/super/users/{id}` |
| POST | `/api/super/users/{id}/password/reset` |
| GET | `/api/super/devices` |
| POST | `/api/super/devices/{id}/revoke` |
| GET | `/api/super/audit` |
| GET | `/api/super/ai-defaults` |
| PATCH | `/api/super/ai-defaults` |
| GET | `/api/super/orgs/{id}/ai-config` |
| PATCH | `/api/super/orgs/{id}/ai-config/locks` |
| PATCH | `/api/super/orgs/{id}/ai-config/settings` |

## Gov admin

| Method | Path |
|---|---|
| GET | `/api/gov/dashboard` |
| GET | `/api/gov/applications` |
| GET | `/api/gov/applications/{id}` |
| PATCH | `/api/gov/applications/{id}` |
| GET | `/api/gov/sessions` |
| GET | `/api/gov/sessions/{id}` |
| GET | `/api/gov/settings/ai` |
| PATCH | `/api/gov/settings/ai/sections/{section_key}` |
| PATCH | `/api/gov/settings/ai/screens/{screen_key}` |
| POST | `/api/gov/settings/ai/officials` |
| PATCH | `/api/gov/settings/ai/officials/{id}` |
| DELETE | `/api/gov/settings/ai/officials/{id}` |
| GET | `/api/gov/staff` |
| POST | `/api/gov/staff` |
| PATCH | `/api/gov/staff/{id}` |
| POST | `/api/gov/staff/{id}/password/reset` |

## WebSocket frame protocol

### Client → Server

- **Binary**: 16 kHz mono PCM16LE audio frames
- **Text JSON**:
  - `{ "type": "screen_context", "screen": "home" | "reception" | "submit" | "contacts" }`

### Server → Client

- **Binary**: 24 kHz mono PCM16LE audio
- **Text JSON**:
  - `{ "type": "transcript", "text": "...", "final": bool, "speaker": "user"|"assistant" }`
  - `{ "type": "audio_done" }`
  - `{ "type": "navigate", "screen": "home" }`
  - `{ "type": "application_preview", "topic": "...", "body": "...", "phone": "..." }`
  - `{ "type": "application_submitted", "id": "uuid", "topic": "...", "body": "...", "phone": "..." }`
  - `{ "type": "error", "code": "E_PRV_001", "message": "..." }`
  - `{ "type": "disconnected" }`
