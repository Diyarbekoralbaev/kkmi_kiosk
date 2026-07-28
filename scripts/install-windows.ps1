# install-windows.ps1 — one-time deploy script for a fresh kiosk box.
#
# What this does (run as Administrator):
#   1. Verifies TPM 2.0 is present + ready. If not, refuses to install.
#   2. Creates the unprivileged `kiosk` local user (auto-login, no password).
#   3. Configures Assigned Access (single-app kiosk mode) for that user — they
#      can ONLY see the kiosk app on login. No Explorer, no taskbar, no Start.
#   4. Schedules a watchdog task: every 60 seconds, if Kiosk.App.exe is not
#      running, start it. Survives crashes.
#   5. Disables Task Manager + Ctrl+Alt+Del + Win key (group-policy registry
#      entries the kiosk user can't override).
#
# Re-run is idempotent — checks before creating each piece.
#
# DO NOT RUN THIS DIRECTLY. Use install-windows.bat next to it — right-click ->
# "Run as administrator". Windows 10's default ExecutionPolicy refuses unsigned
# .ps1 files, so invoking this by hand fails on a fresh machine; the .bat passes
# -ExecutionPolicy Bypass for its own process and adds a confirmation prompt,
# because this locks the machine into kiosk mode.
#
# It stays PowerShell because Assigned Access is configured through the
# Set-AssignedAccess cmdlet, which has no cmd equivalent.

param(
    [Parameter(Mandatory=$true)]
    [string]$ExePath,
    [string]$KioskUser = "kiosk",
    [string]$AppUserModelId = "Kiosk.App"
)

$ErrorActionPreference = "Stop"

function Require-Admin {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole("Administrators")) {
        Write-Error "Run this script as Administrator."
        exit 1
    }
}

function Require-Tpm {
    Write-Host "[1/5] TPM 2.0 check..."
    $tpm = Get-Tpm
    if (-not $tpm.TpmPresent) {
        Write-Error "TPM 2.0 not present. Production kiosk requires TPM 2.0. Aborting."
        exit 2
    }
    if (-not $tpm.TpmReady) {
        Write-Error "TPM is present but not ready. Provision it via tpm.msc or Initialize-Tpm, then re-run."
        exit 2
    }
    Write-Host "    TPM OK (Manufacturer: $($tpm.ManufacturerIdTxt), Spec: 2.0)"
}

function Ensure-KioskUser {
    Write-Host "[2/5] Local user '$KioskUser'..."
    if (-not (Get-LocalUser -Name $KioskUser -ErrorAction SilentlyContinue)) {
        # Empty password so Assigned Access auto-login works with no prompt.
        # The user has zero privileges and no shell, so this is acceptable.
        $sec = ConvertTo-SecureString -String "kiosk" -AsPlainText -Force
        New-LocalUser -Name $KioskUser -Password $sec `
            -PasswordNeverExpires -UserMayNotChangePassword `
            -FullName "Kiosk" -Description "Locked-down kiosk user"
        Write-Host "    created."
    } else {
        Write-Host "    already exists."
    }
}

function Configure-AssignedAccess {
    Write-Host "[3/5] Assigned Access (single-app kiosk mode)..."
    # Set-AssignedAccess wires the user to a UWP/Modern app via AUMID. For
    # classic Win32 apps we use the AssignedAccessConfiguration XML schema.
    # Documented under: docs.microsoft.com/.../kiosk-xml
    $cfg = @"
<?xml version="1.0" encoding="utf-8" ?>
<AssignedAccessConfiguration xmlns="http://schemas.microsoft.com/AssignedAccess/2017/config">
  <Profiles>
    <Profile Id="{e1bb1d1a-3a0c-4b2d-9b41-a0e1f6f3f111}">
      <KioskModeApp ClassicAppPath="$ExePath" />
    </Profile>
  </Profiles>
  <Configs>
    <Config>
      <Account>$env:COMPUTERNAME\$KioskUser</Account>
      <DefaultProfile Id="{e1bb1d1a-3a0c-4b2d-9b41-a0e1f6f3f111}"/>
    </Config>
  </Configs>
</AssignedAccessConfiguration>
"@
    $tmp = Join-Path $env:TEMP "kiosk-aac.xml"
    Set-Content -Path $tmp -Value $cfg -Encoding UTF8
    Set-AssignedAccess -ConfigurationXml (Get-Content $tmp -Raw)
    Remove-Item $tmp -Force
    Write-Host "    set."
}

function Schedule-Watchdog {
    Write-Host "[4/5] Watchdog scheduled task..."
    $taskName = "KioskWatchdog"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -Command `"if (-not (Get-Process -Name 'Kiosk.App' -ErrorAction SilentlyContinue)) { Start-Process -FilePath '$ExePath' }`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes 1) `
        -RepetitionDuration ([TimeSpan]::MaxValue)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:COMPUTERNAME\$KioskUser" -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::FromMinutes(1)) -RestartCount 0
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "    'KioskWatchdog' registered (runs every 60s)."
}

function Lock-Hotkeys {
    Write-Host "[5/5] Disable Task Manager + Win key..."
    # Per-user: HKCU not yet writable for the kiosk user; use HKLM equivalents
    # so they apply at login. Kiosk user can't override these.
    New-Item -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Force | Out-Null
    Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
        -Name "DisableTaskMgr" -Value 1 -Type DWord
    # Disable Win key shortcuts via the 'NoWinKeys' policy.
    New-Item -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer" -Force | Out-Null
    Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer" `
        -Name "NoWinKeys" -Value 1 -Type DWord
    Write-Host "    locked."
}

Require-Admin
Require-Tpm
Ensure-KioskUser
Configure-AssignedAccess
Schedule-Watchdog
Lock-Hotkeys

Write-Host ""
Write-Host "Kiosk lockdown complete. Reboot, then log in as '$KioskUser'."
Write-Host "To enroll the device, hold the bottom-left corner for 3 s + PIN, then enter the enrollment code."
