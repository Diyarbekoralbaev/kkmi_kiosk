#!/usr/bin/env bash
# Linux AOT publish — used for development AOT smoke-tests and the optional
# Linux dev build. Production target is Windows (publish.win.sh).
#
# Usage:
#   ./publish.linux.sh        # Native AOT into publish/linux-x64/
#   ./publish.linux.sh nojit  # Self-contained but JIT'd (faster build, larger bin)
set -euo pipefail

cd "$(dirname "$0")"
RID=${RID:-linux-x64}
OUT=publish/$RID
PROJ=src/Kiosk.App/Kiosk.App.csproj
VERSION=${VERSION:-0.1.0}

rm -rf "$OUT"

if [ "${1:-}" = "nojit" ]; then
  dotnet publish "$PROJ" \
    -c Release \
    -r "$RID" \
    --self-contained true \
    -p:PublishSingleFile=false \
    -p:PublishTrimmed=false \
    -p:Version="$VERSION" \
    -o "$OUT"
  echo "JIT publish: $OUT/Kiosk.App"
  exit 0
fi

# AOT publish — same flags as publish.win.sh; here mainly to validate that
# the codebase stays AOT-clean on Linux.
dotnet publish "$PROJ" \
  -c Release \
  -r "$RID" \
  -p:PublishAot=true \
  -p:Version="$VERSION" \
  -o "$OUT"

BIN="$OUT/Kiosk.App"
echo
echo "Native AOT publish complete: $BIN ($(du -h "$BIN" | cut -f1))"

# Same focused leak audit as the Windows build.
echo
echo "=== sensitive strings audit ==="
LEAKS=$(strings "$BIN" 2>/dev/null | grep -iE \
  'gemini-[0-9]|googleapis\.|generativelanguage|api\.openai|api\.anthropic|sk-[a-zA-Z0-9]{20}|AIza[0-9A-Za-z_-]{30}' \
  || true)
if [ -n "$LEAKS" ]; then
  echo "FAILED: sensitive strings in binary:" >&2
  echo "$LEAKS" >&2
  exit 1
fi
echo "(none) — OK"
