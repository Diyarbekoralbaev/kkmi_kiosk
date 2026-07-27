# KKMI — deployment credentials & server reference

This is the **Joqari Keńes** (Supreme Council) kiosk platform — a clone of the
Hokimiyat kiosk (`kiosk_gov`), deployed as a **separate, isolated stack**.

> ⚠️ **Golden rule: this deploys as a NEW version and must NOT touch the
> existing `kiosk_gov` deployment.** Different compose project name, different
> host ports, different database, different domains, different bot. The two
> stacks can run side by side on the same server without colliding.

## Isolation (already migrated in the repo)

| Resource | kiosk_gov (existing — don't touch) | kkmi_kiosk (this) |
|---|---|---|
| compose `name` | `kiosk-gov` | `kkmi-kiosk` |
| volumes / network | `kiosk-gov_*` | `kkmi-kiosk_*` (auto) |
| database | `kiosk_gov` | `kkmi_kiosk` |
| prod host ports | 8001 / 8002 / 8003 / 8005 | **8031 / 8032 / 8033** |
| dev postgres port | 5433 | **5443** |
| kiosk key storage path | `…/kiosk-gov/` | `…/kkmi-kiosk/` |

Prod host ports map: backend `8031`, super-panel `8032`, gov-panel `8033`,
gatus(status) `8035` — not started, no status subdomain is allocated.
The host nginx proxies the three kkmi domains to the first three.

> Dev panel ports (5173/5174) were left unchanged — fine for running one dev
> stack at a time. If you ever run both dev stacks simultaneously, shift these
> + the matching `CORS_ORIGINS`.

## Credentials checklist — ALL must be FRESH (never reuse kiosk_gov's)

Copy `.env.prod.example` → `.env.prod` on the server and fill every value.

| Variable | How to obtain | Reuse from kiosk_gov? |
|---|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -base64 36` | ❌ new |
| `JWT_SECRET` | `openssl rand -base64 48` | ❌ new |
| `SUPER_ADMIN_EMAIL` / `_PASSWORD` | choose; password `openssl rand -base64 24` | ❌ new |
| `GOOGLE_API_KEY` | Google AI Studio key (Gemini) | may reuse or new key |
| `TELEGRAM_BOT_TOKEN` | **new** bot via @BotFather | ❌ new bot |
| `TELEGRAM_MURAJAT_CHANNEL_ID` / `_QABUL_CHANNEL_ID` | new council channels, bot = admin | ❌ new |
| `HEALTH_DEEP_TOKEN` | `openssl rand -hex 16` | ❌ new |
| `NTFY_TOPIC` | `kkmi-ops-$(openssl rand -hex 4)` | ❌ new |

### Cloudflare relays (Gemini + Telegram) — reusable, with one caveat

The CF Worker relays are **generic forwarders** (Gemini relay → Google;
Telegram relay → api.telegram.org). They carry no kiosk_gov-specific data, so
this project **can reuse the same Workers**:

- `GEMINI_RELAY_URL` + `GEMINI_RELAY_TOKEN` — reuse as-is.
- `TELEGRAM_API_BASE` (telegram relay URL) + `TELEGRAM_RELAY_TOKEN` — reuse
  as-is. Only the **bot token + channel IDs** differ (above).

Why a relay is needed at all: the prod server is in Moscow, where direct
WebSocket-to-Google and HTTPS-to-Telegram are blocked/throttled. The relays
sit on Cloudflare's edge and forward. (See ARCHITECTURE.md / DEPLOY.md.)

> ⚠️ **Known Moscow gotcha:** WebSocket upgrades to Cloudflare get DPI-blocked
> intermittently; plain HTTPS to CF works. If the AI assistant "goes down" but
> the relay answers a plain GET, suspect WS-to-CF — NOT the relay. Also: never
> run `iptables -F` on the host — it wipes Docker's NAT rules and silently
> breaks all container outbound networking (`systemctl restart docker` to fix).

## Domains — TODO (need council values)

`.env.prod.example` still carries the kiosk_gov subdomains as placeholders.
Replace with the council's own subdomains before deploy, e.g.:

```
api.<kkmi-domain>     → backend (8031)
gov.<kkmi-domain>     → gov/operator SPA (8033)
super.<kkmi-domain>   → super-admin SPA (8032)
(no status host — gatus lives behind the `status` compose profile)
```

TLS: issue a multi-SAN cert named `kkmi-kiosk` (the nginx vhosts reference
`/etc/letsencrypt/live/kkmi-kiosk/`). DNS for the council domain is on
Timeweb (not Cloudflare) — HTTP-01 from Moscow can be flaky; DNS-01 is more
reliable if the zone supports it.

## Server access

- Existing prod (kiosk_gov, **do not disturb**): `root@72.56.246.212` (Moscow),
  SSH key-based (no password). This server CAN host kkmi_kiosk alongside it —
  the port/name/db isolation above keeps them separate.
- Target server for kkmi_kiosk: **TBD** — confirm whether it co-locates on
  72.56.246.212 or gets its own box before deploying.

## Backup (restic → Cloudflare R2)

kiosk_gov backs up DB + `.env.prod` + photos to R2 nightly (restic, keep-last
7). Replicate for kkmi_kiosk with a **separate R2 bucket** (e.g.
`joqari-kkmi-backups`) and a **new restic password** (store it outside the
repo; losing it makes backups unreadable). See the kiosk_gov backup script as
the template.
