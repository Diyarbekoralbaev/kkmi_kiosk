#!/usr/bin/env bash
# KKMI server setup — TLS cert (HTTP-01 webroot) + nginx vhosts.
#
# ⚠️ CO-LOCATION SAFE. This host runs several other stacks (joqari_kenes,
# kiosk_gov, moynaq, kkv-platform, kaa-corpus, argus). The script is strictly
# ADDITIVE: it only ever creates/updates the three `kkmi-*.conf` vhosts and the
# `kkmi` certificate. It NEVER removes another vhost, NEVER touches the
# `default` site, and NEVER installs a default_server. Idempotent — safe to
# re-run after a cert renewal or a vhost edit.
#
# Prereqs: nginx, certbot, openssl installed; the three subdomains already
# resolve to this host.
#
# Usage: sudo bash /root/kkmi_kiosk/scripts/server-setup.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERT_NAME=kkmi
EMAIL=admin@diyarbek.uz
DOMAINS=(
  kkmi.diyarbek.uz
  kkmi-api.diyarbek.uz
  kkmi-super.diyarbek.uz
)
ACME_VHOST=/etc/nginx/sites-available/_kkmi-acme.conf

echo "[0/4] Baseline nginx -t (must already be clean)"
nginx -t

echo "[1/4] Temp ACME vhost for the kkmi domains only (additive)"
mkdir -p /var/www/html/.well-known/acme-challenge
{
  echo "# TEMPORARY — KKMI ACME bootstrap. Matches only the three kkmi names."
  echo "server {"
  echo "    listen 80;"
  echo "    listen [::]:80;"
  echo "    server_name ${DOMAINS[*]};"
  echo "    location /.well-known/acme-challenge/ { root /var/www/html; }"
  echo "    location / { return 200 'kkmi-bootstrap\\n'; add_header Content-Type text/plain; }"
  echo "}"
} > "$ACME_VHOST"
ln -sf "$ACME_VHOST" /etc/nginx/sites-enabled/_kkmi-acme.conf
nginx -t
systemctl reload nginx

echo "[2/4] Issue Let's Encrypt multi-SAN cert (HTTP-01 webroot)"
ARGS=(--non-interactive --agree-tos --email "$EMAIL" --webroot -w /var/www/html)
ARGS+=(--cert-name "$CERT_NAME" --keep-until-expiring)
for d in "${DOMAINS[@]}"; do ARGS+=(-d "$d"); done
certbot certonly "${ARGS[@]}"
ls -la /etc/letsencrypt/live/"$CERT_NAME"/

echo "[3/4] Install KKMI vhosts + remove temp ACME vhost"
install -m 644 "$REPO_ROOT/nginx/"kkmi-*.conf /etc/nginx/sites-available/
for f in "$REPO_ROOT/nginx/"kkmi-*.conf; do
  ln -sf "/etc/nginx/sites-available/$(basename "$f")" "/etc/nginx/sites-enabled/$(basename "$f")"
done
rm -f /etc/nginx/sites-enabled/_kkmi-acme.conf
nginx -t
systemctl reload nginx

echo "[4/4] Done"
echo
echo "✓ Cert at /etc/letsencrypt/live/$CERT_NAME/ (SANs: ${DOMAINS[*]})"
echo "✓ KKMI vhosts active — every other site on this host untouched."
echo "✓ Auto-renewal via certbot.timer."
