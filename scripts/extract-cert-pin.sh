#!/usr/bin/env bash
# Extract the SHA-256 fingerprint of a TLS leaf cert for kiosk pinning.
#
# Usage:
#   ./extract-cert-pin.sh kiosk-api.example.uz [port]
#
# Outputs the uppercase hex with no colons — feed this into
# `KIOSK_CERT_PIN_SHA256=...` when running publish.win.sh.
#
# When to re-run:
#   - After cert renewal (Let's Encrypt rotates every ~60 days). The pinned
#     fingerprint changes; build a new kiosk binary and ship via the update
#     channel BEFORE the old cert expires, otherwise kiosks lock themselves
#     out by rejecting the new cert.
set -euo pipefail

HOST="${1:-}"
PORT="${2:-443}"
[ -z "$HOST" ] && { echo "usage: $0 <host> [port]" >&2; exit 2; }

# Pull leaf cert. -servername sets SNI so we hit the right vhost.
PEM=$(echo | openssl s_client -servername "$HOST" -connect "$HOST:$PORT" 2>/dev/null \
  | openssl x509 -outform PEM)
[ -z "$PEM" ] && { echo "could not fetch cert from $HOST:$PORT" >&2; exit 1; }

FP=$(echo "$PEM" | openssl x509 -noout -fingerprint -sha256 \
  | sed -e 's/^SHA256 Fingerprint=//' -e 's/://g' \
  | tr 'a-f' 'A-F')

echo "$FP"
