# archive/

Old code from before the `rebuild/v2` rewrite. Kept for reference and one-time data migration. **Not built, not deployed, not tested**.

## What's here

| Path | Was | Why archived |
|---|---|---|
| `old_admin_ui/` | FastAPI backend + React frontend (single SPA, 8 pages) | Replaced by `apps/backend/` + `apps/super-panel/` + `apps/gov-panel/` (multi-tenant, RBAC, MFA, opaque error codes, Postgres) |
| `old_kiosk_ui/` | React 19 + Vite kiosk frontend (browser-based) | Replaced by C# Avalonia kiosk app in **next plan** (TPM-bound mTLS, signed binary) |
| `old_src/` | Python "engine" (legacy AVA / Asterisk telephony code: ARI, RTP, AudioSocket, mu-law, tools registry, MCP, modular pipelines). `providers/google_live.py` was the only kiosk-relevant file (2662 lines, mostly dead paths) | Replaced by `apps/backend/src/ai/gemini_live.py` — clean rewrite using `google-genai` SDK, no telephony code |
| `old_config/` | `ai-agent.yaml` + `users.json` + golden baselines | YAML AI config replaced by **Postgres tables** (`system_ai_defaults`, `org_prompt_sections`, ...). Users moved to `users` table. **`ai-agent.yaml` is the seed source** for the one-time migration |
| `old_data/` | SQLite DBs (`kiosk_sessions.db`, `call_history.db`, `outbound.db`) | Replaced by Postgres. Kept for reference / future manual migration |
| `old_public/` | Static assets (Sketchfab Humanoid GLB model) for kiosk_ui | Will be re-bundled with Avalonia in next plan |
| `old_docker-compose.yml` / `old_dockerignore` / `old_requirements.txt` / `old_test_kiosk_voice.py` / `old_env_example` | Root-level configs | New equivalents in `deploy/` and `apps/backend/` |

## Reference notes

- The old Karakalpak AI prompt is in `old_config/ai-agent.yaml` lines 4–95. The seed migration (Slice 6) reads this file to populate `system_ai_defaults` and the default Nukus org's `org_prompt_sections` + `org_kb_officials`.
- The 6 Nukus officials (hokim + 5 deputies) listed at lines 72–95 of the old YAML go into `org_kb_officials` for the default Nukus Hokimiyat org.

## Do not import

The new code under `apps/` must not `import` anything from `archive/`. The seed migration is the only allowed touch point, and it reads the YAML as text.
