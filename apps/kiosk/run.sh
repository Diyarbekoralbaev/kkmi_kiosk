#!/usr/bin/env bash
# Dev launcher for the kiosk app. Uses the "pulse" PortAudio device
# (KIOSK_AUDIO_INPUT=8) which routes through PipeWire's echo_cancel_source
# on this machine. Override the env var if your default mic differs.
set -euo pipefail
cd "$(dirname "$0")"
exec env KIOSK_AUDIO_INPUT="${KIOSK_AUDIO_INPUT:-8}" \
     dotnet run --project src/Kiosk.App "$@"
