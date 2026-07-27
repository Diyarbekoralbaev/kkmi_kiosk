# Manual Deploy Runbook

CI/CD scope is intentionally minimal:
- **Backend + 2 SPAs**: built and deployed manually on the server (`git pull`
  + `docker compose up`). No CI involvement.
- **Kiosk Windows .exe**: built automatically by GitHub Actions on every
  `master` push that touches `apps/kiosk/**` (or via manual workflow_dispatch),
  uploaded as a GitHub Release asset.

Server: `82.148.3.38` (Ubuntu 24.04, Servercore Tashkent — same-region as
end users, low latency, clean peering).

Domains (DNS at Timeweb, A records → server IP):
- `kkmi-api.diyarbek.uz` — backend (FastAPI + WS)
- `kkmi-super.diyarbek.uz` — super admin SPA
- `kkmi.diyarbek.uz` — gov admin SPA + public booking/verify

---

## One-time server setup

### 1. Apt prerequisites

```bash
ssh root@82.148.3.38
apt-get update
apt-get install -y docker.io docker-compose-v2 nginx certbot \
  python3-certbot-nginx git ufw fail2ban curl jq openssl
systemctl enable --now docker nginx fail2ban
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

### 2. Clone the repo

```bash
# Generate a deploy key on the server, then add the public part to the GitHub
# repo at: Settings → Deploy keys → Add (read-only is sufficient).
ssh-keygen -t ed25519 -N '' -f /root/.ssh/id_ed25519_github -C "kiosk-deploy@$(hostname)"
cat /root/.ssh/id_ed25519_github.pub
# Paste output above into GitHub repo deploy keys, then:
cat >>/root/.ssh/config <<'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile /root/.ssh/id_ed25519_github
  IdentitiesOnly yes
EOF
chmod 600 /root/.ssh/config
ssh -o StrictHostKeyChecking=accept-new -T git@github.com || true   # accept host key
git clone git@github.com:Diyarbekoralbaev/joqari_kenes.git /root/joqari_kenes
```

### 3. TLS cert (multi-SAN, all 3 subdomains) + nginx vhosts

```bash
bash /root/joqari_kenes/scripts/server-setup.sh
```

The script:
1. Stands up a temporary HTTP-only vhost on port 80 that serves
   `/.well-known/acme-challenge/` from `/var/www/html`.
2. Issues a multi-SAN Let's Encrypt cert via HTTP-01 webroot challenge,
   covering all 3 subdomains, named `joqari-kenes`.
3. Installs the prod vhosts (port 80 → 443 redirect + TLS) and removes the
   bootstrap one.

Auto-renewal is handled by `certbot.timer` (Ubuntu's systemd timer, runs twice
daily). Verify with `systemctl list-timers | grep certbot`.

### 4. `.env.prod`

```bash
cp /root/joqari_kenes/.env.prod.example /root/joqari_kenes/.env.prod
chmod 600 /root/joqari_kenes/.env.prod
nano /root/joqari_kenes/.env.prod
```

Fill in:

| Variable | How |
|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -base64 48` |
| `JWT_SECRET` | `openssl rand -base64 48` |
| `SUPER_ADMIN_PASSWORD` | `openssl rand -base64 24` (or memorable strong password) |
| `GOOGLE_API_KEY` | from Google AI Studio (Gemini Live) |
| `GITHUB_TOKEN` | fine-grained PAT, `Contents: Read` on this repo |
| `GITHUB_WEBHOOK_SECRET` | `openssl rand -hex 16` |

Already set in `.env.prod.example`:
- `PUBLIC_BASE_URL=https://kkmi.diyarbek.uz`
- `CORS_ORIGINS=["https://kkmi-super.diyarbek.uz","https://kkmi.diyarbek.uz"]`
- `KIOSK_GITHUB_REPO=diyarbekoralbaev/joqari_kenes`
- `KIOSK_AUTO_PUBLISH_ON_GITHUB_SYNC=false` (super-admin must click Publish)

### 5. Bring up the stack

```bash
cd /root/joqari_kenes
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml logs -f backend   # watch alembic + startup
```

The backend exposes `127.0.0.1:8001`, super-panel `127.0.0.1:8002`,
gov-panel `127.0.0.1:8003`. nginx proxies all three from 443.

### 6. Smoke test

```bash
curl -fsS https://kkmi-api.diyarbek.uz/health        # → {"status":"ok","db":"ok"}
curl -fsS https://kkmi-super.diyarbek.uz/  -o /dev/null -w "%{http_code}\n"   # → 200
curl -fsS https://kkmi.diyarbek.uz/    -o /dev/null -w "%{http_code}\n"   # → 200
```

Login at `https://kkmi-super.diyarbek.uz/login` with `SUPER_ADMIN_EMAIL` /
`SUPER_ADMIN_PASSWORD` from `.env.prod`. First login enrolls TOTP (MFA
required for super admin).

---

## Routine deploy

```bash
ssh root@82.148.3.38
cd /root/joqari_kenes
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml logs -f backend
```

If nginx vhosts changed in the repo, re-run `bash scripts/server-setup.sh`
(it's idempotent — it'll skip cert renewal if still valid, and refresh the
vhost configs).

---

## Kiosk Windows .exe (CI/CD)

Triggers on every `master` push that changes `apps/kiosk/**` (or manual run
via Actions UI). Workflow: `.github/workflows/build-kiosk.yml`.

```bash
git add apps/kiosk/...
git commit -m "kiosk: ..."
git push origin master
```

Each successful run creates a GitHub Release tagged `kiosk-0.YY.MMDD.HHMM`
with the Velopack `.nupkg` + `Setup.exe` attached.

Pipeline:
1. GitHub Actions runs `windows-latest` runner.
2. `apps/kiosk/publish.win.sh velopack` — Native AOT compile + Velopack pack.
3. Cert pin (`KIOSK_CERT_PIN_SHA256`) baked into the binary via repo Actions
   secret.
4. `.nupkg` + `.exe` uploaded as a GitHub Release asset.
5. GitHub fires a `release` webhook to
   `https://kkmi-api.diyarbek.uz/api/super/releases/github-webhook` →
   backend HMAC-verifies, downloads asset, inserts a draft row in
   `kiosk_releases`.
6. Super-admin sees it in `/releases` → clicks **Publish** → online kiosks
   pick up the update on next check.

### Setting the cert pin secret

The kiosk binary pins the leaf cert SHA-256 of `kkmi-api.diyarbek.uz`. Re-run
after Let's Encrypt rotates the cert (every ~60 days), then push a new build
so existing kiosks can update before the old cert pin expires.

```bash
PIN=$(bash scripts/extract-cert-pin.sh kkmi-api.diyarbek.uz)
gh secret set KIOSK_CERT_PIN_SHA256 --repo Diyarbekoralbaev/joqari_kenes --body "$PIN"
```

### Setting up the GitHub Release webhook

```bash
SECRET="$(awk -F= '/^GITHUB_WEBHOOK_SECRET=/{print $2}' /root/joqari_kenes/.env.prod)"
gh api -X POST repos/Diyarbekoralbaev/joqari_kenes/hooks \
  -f "name=web" -F "active=true" -f "events[]=release" \
  -f "config[url]=https://kkmi-api.diyarbek.uz/api/super/releases/github-webhook" \
  -f "config[content_type]=json" \
  -f "config[secret]=$SECRET" \
  -f "config[insecure_ssl]=0"
```

If the webhook delivery fails (e.g., GitHub outage), super-admin can also
trigger a manual sync from the panel → Releases → "GitHub'dan sync" button,
or upload the `Setup.exe` directly via "Yangi yuklash".

---

## Troubleshooting

**Backend container won't start** → `docker compose logs backend`. Likely
missing/wrong value in `.env.prod` (alembic upgrade fails fast on bad DSN).

**nginx vhost cert error** → re-run `bash scripts/server-setup.sh`, then
`nginx -t && systemctl reload nginx`.

**Kiosk binary build (GH Actions) fails** → `KIOSK_CERT_PIN_SHA256` secret
missing or stale (cert rotated). Set it via the command above and push to
master to rebuild.
