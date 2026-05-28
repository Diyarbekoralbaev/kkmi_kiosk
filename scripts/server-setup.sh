#!/usr/bin/env bash
# One-shot server setup: TLS cert (HTTP-01) + nginx vhosts.
# Idempotent — safe to re-run after cert renewal or vhost edits.
#
# Prereqs (already installed by `apt install`):
#   nginx, certbot, openssl
#
# DNS:
#   A records for api/super/gov.kioska.dbc.uz must already point at this host.
#
# Usage:
#   sudo bash /root/joqari_kenes/scripts/server-setup.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERT_NAME=joqari-kenes
EMAIL=admin@diyarbek.uz
DOMAINS=(api.kioska.dbc.uz super.kioska.dbc.uz gov.kioska.dbc.uz)

echo "[1/3] Stage-1 nginx (port 80 only, serves ACME challenges)"
mkdir -p /var/www/html/.well-known/acme-challenge
cat >/etc/nginx/sites-available/_acme-bootstrap.conf <<'EOF'
# Temporary vhost: catches all hosts on port 80, serves ACME challenges,
# returns a 200 OK to anything else. Gets replaced by the prod vhosts after
# the multi-SAN cert is issued.
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    location / {
        return 200 "bootstrap\n";
        add_header Content-Type text/plain;
    }
}
EOF
ln -sf /etc/nginx/sites-available/_acme-bootstrap.conf /etc/nginx/sites-enabled/_acme-bootstrap.conf
# Disable the default Ubuntu page if present (it claims the same default_server slot).
[ -e /etc/nginx/sites-enabled/default ] && rm -f /etc/nginx/sites-enabled/default

# Stash the prod vhosts out of the way for now (they reference the cert that
# doesn't exist yet, so nginx -t would fail).
for f in /etc/nginx/sites-enabled/kiosk-api.conf /etc/nginx/sites-enabled/super-panel.conf /etc/nginx/sites-enabled/gov-panel.conf; do
  [ -e "$f" ] && rm -f "$f"
done

nginx -t
systemctl reload nginx

echo "[2/3] Issue Let's Encrypt cert via HTTP-01 webroot"
ARGS=(--non-interactive --agree-tos --email "$EMAIL" --webroot -w /var/www/html)
ARGS+=(--cert-name "$CERT_NAME" --keep-until-expiring)
for d in "${DOMAINS[@]}"; do ARGS+=(-d "$d"); done
certbot certonly "${ARGS[@]}"
ls -la /etc/letsencrypt/live/"$CERT_NAME"/

echo "[3/3] Install prod vhosts + remove bootstrap"
install -m 644 "$REPO_ROOT/nginx/"*.conf /etc/nginx/sites-available/
for f in "$REPO_ROOT/nginx/"*.conf; do
  ln -sf "/etc/nginx/sites-available/$(basename "$f")" "/etc/nginx/sites-enabled/$(basename "$f")"
done
rm -f /etc/nginx/sites-enabled/_acme-bootstrap.conf
nginx -t
systemctl reload nginx

echo
echo "✓ Cert at /etc/letsencrypt/live/$CERT_NAME/"
echo "✓ vhosts active for: ${DOMAINS[*]}"
echo "✓ Auto-renewal handled by certbot.timer (twice daily) — verify with: systemctl list-timers | grep certbot"
