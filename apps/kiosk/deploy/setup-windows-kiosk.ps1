# Setup-Windows-Kiosk.ps1
#
# Configures a fresh Windows 11 box as a single-purpose kiosk:
#   - Creates a 'kiosk' local user (no password, can't change it).
#   - Registers Kiosk.App.exe as the "Assigned Access" shell for that user
#     so the desktop, taskbar, and Start menu never appear.
#   - Auto-logon as 'kiosk' on boot.
#   - Creates a scheduled task that re-launches Kiosk.App.exe if it crashes.
#
# Run as Administrator on the target machine.
#
# Usage:
#   .\Setup-Windows-Kiosk.ps1 -InstallPath "C:\Program Files\Kiosk"
#
# Tested on Windows 11 24H2 + .NET 10 runtime. Assigned Access requires the
# Pro / Enterprise / Education edition (Home does not expose the cmdlet).
#
# After running this, reboot. The machine will auto-logon as 'kiosk' and
# launch the kiosk app full-screen with no escape routes (Ctrl+Alt+Del still
# works for the operator — see the optional GP step at the bottom).

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$InstallPath,
    [string]$KioskUser = "kiosk",
    [string]$AppExe = "Kiosk.App.exe"
)

$ErrorActionPreference = "Stop"

function Require-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal $id
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script as Administrator."
    }
}

Require-Admin

$exePath = Join-Path $InstallPath $AppExe
if (-not (Test-Path $exePath)) {
    throw "Kiosk binary not found at $exePath — install it first."
}

Write-Host "[1/5] Creating local user '$KioskUser'..."
if (-not (Get-LocalUser -Name $KioskUser -ErrorAction SilentlyContinue)) {
    $blank = ConvertTo-SecureString " " -AsPlainText -Force
    New-LocalUser -Name $KioskUser -Password $blank -PasswordNeverExpires -UserMayNotChangePassword `
        -Description "Kiosk Gov kiosk shell account" | Out-Null
} else {
    Write-Host "  exists — skipping"
}

# Add to Users group (Assigned Access works only with standard users, not admins).
Write-Host "[2/5] Adding to local Users group..."
Add-LocalGroupMember -Group "Users" -Member $KioskUser -ErrorAction SilentlyContinue | Out-Null

Write-Host "[3/5] Registering Assigned Access (single-app kiosk)..."
# Set-AssignedAccess is the supported, durable way to make a Win32 .exe the
# user's shell. See the MS docs on "Configure a single-app kiosk".
Set-AssignedAccess -UserName $KioskUser -AppExecutable $exePath

Write-Host "[4/5] Configuring auto-logon as $KioskUser..."
$winLogonKey = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
Set-ItemProperty -Path $winLogonKey -Name AutoAdminLogon  -Value "1"
Set-ItemProperty -Path $winLogonKey -Name DefaultUserName -Value $KioskUser
Set-ItemProperty -Path $winLogonKey -Name DefaultPassword -Value " "
Set-ItemProperty -Path $winLogonKey -Name DefaultDomainName -Value $env:COMPUTERNAME

Write-Host "[5/5] Creating watchdog scheduled task..."
# Re-launches the kiosk if Task Manager / a crash kills it. Runs every minute.
$taskName = "KioskGov-Watchdog"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action  = New-ScheduledTaskAction -Execute $exePath
$trigger = New-ScheduledTaskTrigger -AtStartup
$repeat  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $KioskUser -LogonType Interactive
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($trigger, $repeat) `
    -Principal $principal -Settings $settings | Out-Null

Write-Host ""
Write-Host "Done."
Write-Host ""
Write-Host "Next:"
Write-Host "  - Reboot. The box should auto-logon as '$KioskUser' and open Kiosk.App full-screen."
Write-Host "  - If you need to escape: Ctrl+Alt+Del → Switch User → log in as your admin account."
Write-Host "  - To rip out the kiosk config later: Clear-AssignedAccess; Remove-LocalUser $KioskUser."
