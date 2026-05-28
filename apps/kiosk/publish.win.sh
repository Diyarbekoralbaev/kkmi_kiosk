#!/usr/bin/env bash
# Production publish for Windows. Native AOT → single-file native exe, no .NET
# reflection metadata to leak. Velopack then packages the binary into a signed
# delta-update bundle.
#
# Usage:
#   ./publish.win.sh            # AOT bundle into publish/win-x64/
#   ./publish.win.sh velopack   # Same + Velopack pack into Releases/
#
# Env vars:
#   VERSION=0.2.0                # version stamped into the binary + Velopack pack
#   KIOSK_CERT_PIN_SHA256=       # SHA-256 of leaf cert (uppercase hex). Empty
#                                # in dev → cert pinning disabled with a runtime
#                                # warning. Production deploys MUST set this.
#
# Prereqs:
#   - dotnet sdk 10
#   - vpk tool: `dotnet tool install -g vpk`
#   - On Linux dev: cross-compile to win-x64 works for managed code; some native
#     deps (ONNX, PortAudio) ship multi-RID NuGet artifacts so they cross too.
set -euo pipefail

cd "$(dirname "$0")"
RID=win-x64
OUT=publish/$RID
PROJ=src/Kiosk.App/Kiosk.App.csproj

VERSION=${VERSION:-0.1.0}

rm -rf "$OUT"

# Optional pre-AOT injection of the cert pin + backend URL via sed. We replace
# const placeholders in the source so the compiled binary contains only the
# baked value (not the placeholder). Skipped when env vars are empty.
restore_files=()
inject() {
  local pattern="$1"
  local replacement="$2"
  local file="$3"
  # Snapshot original on first inject only — multiple injects can target the
  # same file (cert pin + backend URL both live in PinnedHttpClient.cs); a
  # second cp would overwrite the snapshot with already-modified content.
  if [ ! -f "${file}.bak" ]; then
    cp "$file" "${file}.bak"
    restore_files+=("$file")
  fi
  local tmp
  tmp=$(mktemp)
  sed -E "s|${pattern}|${replacement}|g" "$file" > "$tmp"
  mv "$tmp" "$file"
}

if [ -n "${KIOSK_CERT_PIN_SHA256:-}" ]; then
  echo "[publish] injecting cert pin: ${KIOSK_CERT_PIN_SHA256:0:16}..."
  inject 'public const string CertPinSha256 = "[^"]*";' \
    "public const string CertPinSha256 = \"${KIOSK_CERT_PIN_SHA256}\";" \
    src/Kiosk.App/Net/PinnedHttpClient.cs
fi
trap 'for f in "${restore_files[@]}"; do mv "${f}.bak" "$f" 2>/dev/null || true; done' EXIT

# Native AOT publish. Reflection metadata is gone, IL is gone — dnSpy refuses
# the binary as "not a managed assembly".
dotnet publish "$PROJ" \
  -c Release \
  -r "$RID" \
  -p:PublishAot=true \
  -p:Version="$VERSION" \
  -o "$OUT"

EXE="$OUT/Kiosk.App.exe"
echo
echo "Native AOT publish complete: $EXE ($(du -h "$EXE" | cut -f1))"

# Sensitive-string audit. We focus on patterns that would be a REAL leak —
# vendor-specific API hostnames, model names, key shapes. Generic words like
# "google" or "prompt" are excluded because they show up in Brotli's static
# dictionary that every .NET app embeds (false positive).
echo
echo "=== sensitive strings audit ==="
LEAKS=$(strings "$EXE" 2>/dev/null | grep -iE \
  'gemini-[0-9]|googleapis\.|generativelanguage|api\.openai|api\.anthropic|sk-[a-zA-Z0-9]{20}|AIza[0-9A-Za-z_-]{30}' \
  || true)
if [ -n "$LEAKS" ]; then
  echo "FAILED: sensitive strings in binary:" >&2
  echo "$LEAKS" >&2
  exit 1
fi
echo "(none) — OK"

if [ "${1:-}" = "velopack" ]; then
  echo
  echo "=== velopack pack ==="
  command -v vpk >/dev/null 2>&1 || { echo "vpk not installed: dotnet tool install -g vpk" >&2; exit 2; }
  mkdir -p Releases
  vpk pack \
    --packId "Kiosk" \
    --packVersion "$VERSION" \
    --packDir "$OUT" \
    --mainExe "Kiosk.App.exe" \
    --outputDir Releases
fi
