#!/usr/bin/env bash
# install-linux.sh — DEV/test kiosk lockdown on Linux. Production target is
# Windows, but a Linux box is useful for CI smoke-tests and early integration.
#
# Sets up a systemd --user service that auto-restarts the kiosk binary, and
# documents the manual steps for a fully locked desktop (openbox single-app).
set -euo pipefail

EXE="${1:-$HOME/kiosk/Kiosk.App}"
[ -x "$EXE" ] || { echo "missing or non-executable: $EXE" >&2; exit 1; }

UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/kiosk.service" <<EOF
[Unit]
Description=Kiosk gov client
After=graphical-session.target

[Service]
Type=simple
ExecStart=$EXE
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now kiosk.service

cat <<MSG

Kiosk service installed (linux user systemd unit).
  Status:  systemctl --user status kiosk
  Logs:    journalctl --user -u kiosk -f

To turn the desktop into a real kiosk (no taskbar, no escape):
  - Use a minimal WM (openbox / i3) with a single autostart entry pointing here
  - Disable Ctrl+Alt+T, Alt+F2 in the WM config
  - Run X with -nolisten tcp on a dedicated TTY

This Linux path is for development convenience; production = Windows + TPM.
MSG
