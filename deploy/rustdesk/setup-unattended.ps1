# RustDesk unattended access for a KKMI kiosk.
#
# Problem this solves: out of the box RustDesk runs in "Accept sessions via
# click" mode, so every incoming connection waits for somebody standing at the
# kiosk to press Accept — and a file transfer opens a SECOND session, so it
# prompts again. Nobody is standing at a lobby kiosk, so both prompts time out
# and the connection fails.
#
# Fix, in order (all three are required — any one alone is not enough):
#   1. INSTALL RustDesk (not portable). Only an installed copy registers the
#      Windows service, and only the service survives logout, the lock screen
#      and UAC elevation. A portable rustdesk.exe drops the session the moment
#      the desktop changes.
#   2. Set a PERMANENT password and tell RustDesk to accept it
#      (verification-method = use-permanent-password).
#   3. Switch approve-mode to `password`, so a valid password IS the approval
#      and no click is ever required — for screen control and file transfer
#      alike, since a file transfer is just another session.
#
# Run from an ELEVATED PowerShell. `--password` and `--option` both refuse to
# do anything unless RustDesk is installed AND the caller is admin (see
# rustdesk/src/core_main.rs).
#
#   .\setup-unattended.ps1 -Password 'YourStrongPassword'
#   .\setup-unattended.ps1 -Password 'YourStrongPassword' -Installer .\rustdesk-1.4.4-x86_64.exe

[CmdletBinding()]
param(
    # The fixed password remote support will type. Pick something long — this
    # is the only thing standing between the internet and a machine in a public
    # hall, and RustDesk IDs are enumerable.
    [Parameter(Mandatory = $true)]
    [ValidateLength(12, 128)]
    [string]$Password,

    # Path to the RustDesk installer. Omit if RustDesk is already installed.
    [string]$Installer,

    # Leave file transfer enabled. Set to $false on kiosks where support should
    # be able to look but not copy anything off the machine.
    [bool]$AllowFileTransfer = $true
)

$ErrorActionPreference = 'Stop'

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Elevated PowerShell required — RustDesk ignores --password and --option otherwise."
    }
}

function Find-RustDesk {
    $candidates = @(
        "$env:ProgramFiles\RustDesk\rustdesk.exe",
        "${env:ProgramFiles(x86)}\RustDesk\rustdesk.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

Assert-Admin

# ── 1. Install ────────────────────────────────────────────────────────────────
$exe = Find-RustDesk
if (-not $exe) {
    if (-not $Installer) {
        throw "RustDesk is not installed and no -Installer was given. Download it from https://rustdesk.com/ and pass the path."
    }
    if (-not (Test-Path $Installer)) { throw "Installer not found: $Installer" }

    Write-Host "[1/4] Installing RustDesk (silent)..."
    # --silent-install installs AND registers the service; the interactive
    # installer's "Run as service" checkbox is the same thing.
    Start-Process -FilePath (Resolve-Path $Installer) -ArgumentList '--silent-install' -Wait

    # The installer returns before the service is fully up.
    for ($i = 0; $i -lt 30 -and -not (Find-RustDesk); $i++) { Start-Sleep -Seconds 1 }
    $exe = Find-RustDesk
    if (-not $exe) { throw "Install finished but rustdesk.exe was not found." }
} else {
    Write-Host "[1/4] RustDesk already installed: $exe"
}

# ── 2. Service ────────────────────────────────────────────────────────────────
Write-Host "[2/4] Ensuring the service runs and starts at boot..."
$svc = Get-Service -Name 'RustDesk' -ErrorAction SilentlyContinue
if (-not $svc) {
    & $exe --install-service
    Start-Sleep -Seconds 5
    $svc = Get-Service -Name 'RustDesk' -ErrorAction SilentlyContinue
}
if (-not $svc) { throw "The RustDesk service is not registered. Re-run the installer with 'Run as service' ticked." }

Set-Service -Name 'RustDesk' -StartupType Automatic
if ($svc.Status -ne 'Running') { Start-Service -Name 'RustDesk' }

# ── 3. Password + approval mode ───────────────────────────────────────────────
Write-Host "[3/4] Setting the permanent password and approval mode..."

# Order matters: set the password BEFORE switching verification-method, so the
# machine is never briefly in "accept by password" with no password set.
& $exe --password $Password

# use-permanent-password: stop rotating the one-time password, which is
# useless unattended — nobody can read it off the screen.
& $exe --option verification-method use-permanent-password

# password: a correct password IS the approval. This is the setting that kills
# BOTH prompts (screen control and file transfer) — a file transfer is a normal
# session and goes through the same gate.
& $exe --option approve-mode password

& $exe --option enable-file-transfer $(if ($AllowFileTransfer) { 'Y' } else { 'N' })

# Keep support from being locked out by a well-meaning local edit.
& $exe --option disable-change-permanent-password Y

# ── 4. Verify ─────────────────────────────────────────────────────────────────
Write-Host "[4/4] Verifying..."
$id = (& $exe --get-id) -join ''
$checks = @(
    @{ Key = 'verification-method'; Want = 'use-permanent-password' },
    @{ Key = 'approve-mode';        Want = 'password' },
    @{ Key = 'enable-file-transfer'; Want = $(if ($AllowFileTransfer) { 'Y' } else { 'N' }) }
)

$failed = $false
foreach ($c in $checks) {
    $got = ((& $exe --option $c.Key) -join '').Trim()
    $ok = $got -eq $c.Want
    if (-not $ok) { $failed = $true }
    "{0} {1,-24} = {2}" -f $(if ($ok) { 'OK  ' } else { 'FAIL' }), $c.Key, $got | Write-Host
}

Write-Host ""
Write-Host "  RustDesk ID : $id"
Write-Host "  Service     : $((Get-Service RustDesk).Status) / $((Get-Service RustDesk).StartType)"
Write-Host ""

if ($failed) {
    Write-Warning "Some options did not stick. Usual cause: RustDesk was launched from a portable exe rather than the installed copy, so the CLI talked to the wrong instance."
    exit 1
}

Write-Host "Done. Connect with the ID above and the password you set — no prompt on the kiosk, for control or file transfer."
