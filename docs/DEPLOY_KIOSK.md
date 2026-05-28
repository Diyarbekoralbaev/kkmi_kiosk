# Kiosk Windows Deployment Runbook

This is the step-by-step for getting a fresh Windows machine into production
as a locked-down kiosk.

## Prerequisites

- Windows 10 (build 1909+) or Windows 11. **TPM 2.0 required** (Win 11 always
  has it; check Win 10 with `Get-Tpm`).
- Touchscreen monitor (1920×1080 landscape).
- USB mic + speakers (or a USB conference puck).
- Outbound HTTPS to your kiosk-api.<domain> server.

## 1. Build the kiosk binary

On the build machine (Linux dev or any Windows box with .NET 10 SDK):

```bash
cd apps/kiosk
KIOSK_CERT_PIN_SHA256=<sha256 from extract-cert-pin.sh> \
KIOSK_BACKEND_URL=https://kiosk-api.example.uz \
VERSION=0.2.0 \
./publish.win.sh velopack
```

This produces:
- `apps/kiosk/publish/win-x64/Kiosk.App.exe` — Native AOT, ~30 MB. dnSpy refuses
  the binary as "not a managed assembly". Sensitive-string audit ran.
- `apps/kiosk/Releases/Kiosk-0.2.0-Setup.exe` — Velopack installer + delta.

## 2. Upload the release to the backend

In the super-panel:

1. Navigate to **Releases**.
2. Click **Yangi yuklash**, attach `Kiosk-0.2.0-Setup.exe`, set version `0.2.0`,
   channel `stable`, write release notes, optionally tick *mandatory*.
3. Once uploaded, click **Publish**. From this moment every kiosk that contacts
   the backend on startup downloads + applies this build before voice opens.

(Alternative: configure `KIOSK_GITHUB_REPO=owner/repo` env var on the backend
and click **GitHub'dan sync** to pull the latest release asset automatically.)

## 3. First-time install on the kiosk machine

Log in as a **local administrator** (this is one-time; the kiosk user comes next).

```powershell
# Copy Kiosk-0.2.0-Setup.exe to the box, run it. UAC prompt appears once —
# click "Yes". Velopack writes to %LocalAppData%\Kiosk\.
.\Kiosk-0.2.0-Setup.exe

# Run the lockdown script (provided in deploy/scripts/install-windows.ps1).
Set-ExecutionPolicy -Scope Process Bypass
.\install-windows.ps1 -ExePath "$env:LocalAppData\Kiosk\current\Kiosk.App.exe"
```

The script:
- Verifies TPM 2.0 is present (refuses install otherwise)
- Creates a `kiosk` local user (no admin)
- Sets up Assigned Access — that user sees only Kiosk.App on login
- Schedules a 60-second watchdog (auto-restart on crash)
- Disables Task Manager + Win key

Reboot. The box auto-logs in as `kiosk` and the app fills the screen.

## 4. Enroll the device

In super-panel → Devices → **+ New device**. Copy the 12-char enrollment code
(shown ONCE).

On the kiosk:
- Hold the bottom-left corner for 3 seconds → PIN dialog.
- Default PIN is `0000`. Type it.
- *(Operator's first time)* admin settings open — pick mic, speaker, printer,
  set test print, save. **First-time enrollment** dialog auto-opens if no
  device key exists yet — type the 12-char code.

The kiosk:
- Generates an ECDSA P-256 keypair **inside the TPM** (NCryptCreatePersistedKey).
- Sends only the public PEM to the backend.
- Stores `device_id` + `backend_url` in DPAPI-encrypted file (no shared secret).

Restart the kiosk app from the admin settings (or wait for the watchdog). On
next launch it does the update gate, then opens the home screen with the
robot.

## 5. Day-to-day operations

| Task | Where | What |
|---|---|---|
| Push a new version | super-panel → Releases | Upload + Publish |
| Roll back | super-panel → Releases | Unpublish current; previous published row becomes latest |
| Revoke a kiosk | super-panel → Devices → Revoke | Active WS closes within ~50 ms; kiosk wipes its TPM key + creds; shows red overlay |
| Re-enroll | kiosk → Re-enroll button | New TPM keypair, new device_id |
| Cert renewal | extract-cert-pin.sh + new build | Build & ship a new kiosk version BEFORE the cert rotates |

## 6. Troubleshooting

- **"TPM 2.0 talab qilinadi" on enroll** — `Get-Tpm` shows TpmPresent=False or
  TpmReady=False. Enable TPM in BIOS/UEFI; for Win 10 boxes, use AMD fTPM or
  Intel PTT firmware TPM if no discrete chip.
- **Kiosk shows red "Bul kioskqa ruxsat joq" overlay** — device was revoked
  server-side. Click *Janadan kód kiritsin* and follow step 4 again.
- **Update gate spins forever** — check `kiosk-api.<domain>` is reachable from
  the box; backend logs show `update.check` calls; SHA-256 of the published
  release file matches the uploaded one (CDN/disk corruption check).
- **Cert pin mismatch after Let's Encrypt renewal** — kiosks trust ONLY the
  pinned SHA. Build a new version with the new pin BEFORE the cert rotates,
  publish, let kiosks update, then let the old cert expire.

## 7. Network requirements

Single neutral hostname. The box only ever talks to:

- `https://kiosk-api.<domain>` — backend API + WS (TLS-pinned)
- (optional) `https://<your-update-cdn>/...` if you serve releases off the
  backend (default is the backend itself, also TLS-pinned)

No direct calls to any AI vendor.
