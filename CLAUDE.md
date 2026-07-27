# CLAUDE.md

Guidance for Claude Code working on this repository.

## Project at a glance

AI voice kiosk for the **Karakalpakstan Medical Institute** (KKMI,
Qoraqalpogʻiston tibbiyot instituti — Nukus, HEMIS code 349). A portrait
touchscreen in the lobby answers questions by voice and by touch.

Six services on the home screen:

| Menu | What it does | Data source |
|---|---|---|
| AI Maslahatchi | General study / medical Q&A | Model + prompt KB |
| AI Kutubxona | *Coming soon* — catalogue not connected | — |
| AI Abituriyent | Degree programmes for applicants | HEMIS mirror |
| AI Murojat | File an appeal with the institute | Our `applications` table |
| Dars jadvali | Group timetables | HEMIS mirror |
| Rahbariyat qabuli | Book a reception, prints a ticket | Our `appointments` table |

The codebase was inherited from the Joqarı Keńes (Karakalpakstan Supreme
Council) kiosk and rebuilt for the institute. Anything still mentioning a
council, hokimiyat, districts/mahallas or `cabinet.murajat.uz` is a leftover
worth removing, not a pattern to copy.

## Layout

```
apps/
  backend/          FastAPI + SQLAlchemy 2 async + Alembic + google-genai
  kiosk/            C# Avalonia 12 / .NET 10, Native AOT, portrait 1080×1572
  super-panel/      React 19 SPA — provider admin (port 5173)
  gov-panel/        React 19 SPA — institute admin (port 5174)
docs/               ARCHITECTURE.md, API.md, DEPLOY*.md, SECURITY.md
```

## Common commands

```bash
make up          # postgres + redis + backend + 2 panels
make migrate     # alembic upgrade head
make test        # pytest
make lint        # ruff
make psql        # psql shell into dev postgres
make hemis-sync  # mirror HEMIS into Postgres (~95 s, hits the live API)

cd apps/kiosk && dotnet build src/Kiosk.App/Kiosk.App.csproj
cd apps/kiosk && dotnet run --project src/Kiosk.App -- --ws-test 20 jadval
```

## Architectural rules

- **Tenancy via `core/deps`**. Gov endpoints depend on `OrgAdmin`; kiosk
  endpoints resolve the org from the authenticated device. Never trust an
  `org_id` from a request body.
- **Errors are opaque**. Raise `AppError` subclasses with codes; never return
  raw exception text. The handler logs the real exception under a
  `correlation_id`.
- **Write endpoints call `core/audit.record(...)`**. Reads are not audited.
- **AI config lives in the DB, not files**. `prompt_builder.py` assembles the
  prompt from `system_ai_defaults` rows; edit it through the super panel.
- **One AI provider, one transport**. Gemini Live over a raw WebSocket
  (`ai/gemini_live.py` — the SDK breaks multi-turn on 3.1). `VOICE_BACKEND=kaa`
  swaps in a local STT→LLM→TTS server behind the same interface.
- **Two SPAs, not one**. The duplication between `super-panel/` and
  `gov-panel/` is the security boundary.

## The two things most likely to bite you

**1. Menu scoping.** The kiosk opens the WS as
`/ws/kiosk/voice?menu=<name>`. That single value picks BOTH the prompt's focus
block and the tool set the agent may call (`ai/tools.MENU_TOOLS`). Declaring
every tool at once made the model blend flows — offering to file an appeal when
asked for a timetable. A menu whose focus section is missing still runs, just
dumber, so `prompt_builder` logs `prompt_sections_missing`; adding a menu means
adding its key to `MENU_TOOLS`, `FOCUS_SECTION_KEYS` and `DEFAULT_SECTIONS`
together. `tests/test_prompt_builder.py` enforces that.

**2. The HEMIS mirror is a mirror.** `hemis_*` tables are rebuildable copies of
student.kkmi.uz — never the source of truth, never written to by request
handlers. The sync is a FULL sweep, not incremental: HEMIS exposes no deletion
feed, so an incremental run would leave cancelled classes on screen forever.
Deliberately no foreign keys between the mirrored tables; upstream is
eventually-consistent and FKs would turn a stale reference into a failed sync.

## Auth

- Super admin: MFA required (TOTP), bootstrapped from `SUPER_ADMIN_EMAIL` /
  `SUPER_ADMIN_PASSWORD`.
- Institute admin: MFA optional.
- Argon2id passwords. JWT access (15 min) + refresh (7 days, rotated, hashed).
- Kiosks: TPM-bound keypair, signed-nonce header on every request.

## Privacy stance

The kiosk stands in a public corridor and identifies nobody — by design. Group
timetables and degree programmes are public information. Individual grades,
attendance and debts are NOT exposed, even though HEMIS would serve them: with
no authentication, anyone could read a stranger's record. If personal data is
ever needed here, it needs a real identity check first, not a phone number.

## When in doubt

- New endpoint? `apps/backend/src/api/{super,gov,kiosk_*}` with the matching
  dependency.
- New table? Model in `apps/backend/src/domain/`, register in
  `domain/__init__.py`, write an Alembic migration.
- New error case? Subclass `AppError` with a fresh code in `core/errors.py`.
- New prompt section? Extend `SECTION_KEYS` in `domain/ai_config.py` and seed it
  in `core/seed.py`.
- New kiosk colour? Add a token in `App.axaml`. Code-behind reads it through
  `Palette.Brush(...)` — never a hex literal, that is how 55 stale colours
  accumulated last time.

## Open items

- **AI Kutubxona has no data source.** `irbis.kkmi.uz` does not resolve from
  outside; the institute has not supplied a catalogue export. The tile shows a
  "coming soon" screen and the menu declares no tools.
- **Admission quotas / pass marks / tuition are not in HEMIS.** The agent is
  instructed to refuse to guess them and to point at the admissions committee.
- **Production domains are placeholders** (`kkmi-*.gov.diyarbek.uz` in
  `nginx/` and `.env.prod.example`) — confirm before deploying.
- **The git remote still points at `joqari_kenes`.**

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
