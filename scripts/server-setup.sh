#!/usr/bin/env bash
# Joqarı Keńes server setup — TLS cert (HTTP-01 webroot) + nginx vhosts.
#
# ⚠️ CO-LOCATION SAFE: this host also runs kiosk_gov (+ a cleaning app). This
# script is strictly ADDITIVE — it only ever creates/updates the Council's own
# `kenes-*.conf` vhosts and the `joqari-kenes` cert. It NEVER removes other
# vhosts, NEVER touches the `default` site, and NEVER installs a default_server.
# Idempotent — safe to re-run after cert renewal or vhost edits.
#
# Prereqs: nginx, certbot, openssl already installed; DNS for the 4 kenes-*
# subdomains already resolves to this host (wildcard *.kioska.dbc.uz does).
#
# Usage: sudo bash /root/joqari_kenes/scripts/server-setup.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERT_NAME=joqari-kenes
EMAIL=admin@diyarbek.uz
DOMAINS=(
  kenes-api.kioska.dbc.uz
  kenes-super.kioska.dbc.uz
  kenes-gov.kioska.dbc.uz
  kenes-status.kioska.dbc.uz
)
ACME_VHOST=/etc/nginx/sites-available/_kenes-acme.conf

echo "[0/4] Baseline nginx -t (must already be clean)"
nginx -t

echo "[1/4] Temp ACME vhost for the kenes-* domains only (additive)"
mkdir -p /var/www/html/.well-known/acme-challenge
{
  echo "# TEMPORARY — Council ACME bootstrap. Only matches the 4 kenes-* names."
  echo "server {"
  echo "    listen 80;"
  echo "    listen [::]:80;"
  echo "    server_name ${DOMAINS[*]};"
  echo "    location /.well-known/acme-challenge/ { root /var/www/html; }"
  echo "    location / { return 200 'kenes-bootstrap\\n'; add_header Content-Type text/plain; }"
  echo "}"
} > "$ACME_VHOST"
ln -sf "$ACME_VHOST" /etc/nginx/sites-enabled/_kenes-acme.conf
nginx -t
systemctl reload nginx

echo "[2/4] Issue Let's Encrypt multi-SAN cert (HTTP-01 webroot)"
ARGS=(--non-interactive --agree-tos --email "$EMAIL" --webroot -w /var/www/html)
ARGS+=(--cert-name "$CERT_NAME" --keep-until-expiring)
for d in "${DOMAINS[@]}"; do ARGS+=(-d "$d"); done
certbot certonly "${ARGS[@]}"
ls -la /etc/letsencrypt/live/"$CERT_NAME"/

echo "[3/4] Status-page basic-auth file (create if missing)"
if [ ! -f /etc/nginx/.htpasswd-kenes-status ]; then
  STATUS_PASS="$(openssl rand -base64 12)"
  printf 'kenes:%s\n' "$(openssl passwd -apr1 "$STATUS_PASS")" > /etc/nginx/.htpasswd-kenes-status
  echo "  → created /etc/nginx/.htpasswd-kenes-status  (user: kenes  pass: $STATUS_PASS)"
  echo "  → SAVE THIS PASSWORD — it is shown only once."
fi

echo "[4/4] Install Council vhosts + remove temp ACME vhost"
install -m 644 "$REPO_ROOT/nginx/"kenes-*.conf /etc/nginx/sites-available/
for f in "$REPO_ROOT/nginx/"kenes-*.conf; do
  ln -sf "/etc/nginx/sites-available/$(basename "$f")" "/etc/nginx/sites-enabled/$(basename "$f")"
done
rm -f /etc/nginx/sites-enabled/_kenes-acme.conf
nginx -t
systemctl reload nginx

echo
echo "✓ Cert at /etc/letsencrypt/live/$CERT_NAME/ (SANs: ${DOMAINS[*]})"
echo "✓ Council vhosts active — kiosk_gov + other sites untouched."
echo "✓ Auto-renewal via certbot.timer."
