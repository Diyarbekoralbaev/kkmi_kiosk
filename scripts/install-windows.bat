@echo off
setlocal
REM ============================================================================
REM  KKMI kiosk — one-time Windows setup.
REM
REM  Right-click this file -> "Run as administrator". Nothing else to type.
REM
REM  Why a .bat around a .ps1: Windows 10 ships with an ExecutionPolicy that
REM  refuses unsigned .ps1 files, so running the script directly fails on a
REM  fresh machine — the one place you cannot afford a surprise, because
REM  somebody had to physically walk to it. This wrapper passes
REM  -ExecutionPolicy Bypass for its own process only; the machine's policy is
REM  never changed.
REM
REM  The underlying script genuinely needs PowerShell: Assigned Access (single
REM  app kiosk mode) is configured through the Set-AssignedAccess cmdlet, which
REM  has no cmd equivalent. This is not laziness — it cannot be done in cmd.
REM
REM  What the setup does:
REM    1. Verifies TPM 2.0 is present and ready (refuses to continue if not).
REM    2. Creates the unprivileged `kiosk` local user with auto-login.
REM    3. Assigned Access: that user sees ONLY the kiosk app. No Explorer, no
REM       taskbar, no Start menu.
REM    4. Watchdog task: restarts Kiosk.App.exe within 60 s if it dies.
REM    5. Disables Task Manager, Ctrl+Alt+Del and the Windows key.
REM
REM  AFTER THIS RUNS THE MACHINE LOCKS INTO KIOSK MODE. Set up RustDesk
REM  unattended access FIRST (deploy\rustdesk\setup-unattended.bat), otherwise
REM  getting back in means walking to the kiosk again.
REM
REM  Usage:
REM    install-windows.bat
REM    install-windows.bat "C:\Program Files\Kiosk\Kiosk.App.exe"
REM ============================================================================

set "EXEPATH=%~1"
if "%EXEPATH%"=="" set "EXEPATH=C:\Program Files\Kiosk\Kiosk.App.exe"

net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [X] Administrator required.
    echo       Right-click this file and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

if not exist "%EXEPATH%" (
    echo.
    echo   [X] Kiosk app not found: %EXEPATH%
    echo       Install it first, or pass the path:
    echo         install-windows.bat "C:\path\to\Kiosk.App.exe"
    echo.
    pause
    exit /b 1
)

set "PS1=%~dp0install-windows.ps1"
if not exist "%PS1%" (
    echo   [X] install-windows.ps1 not found next to this file.
    pause
    exit /b 1
)

echo.
echo   This will lock the machine into kiosk mode.
echo   App: %EXEPATH%
echo.
echo   Make sure RustDesk unattended access is already working - after this
echo   runs, remote access is the only easy way back in.
echo.
set /p CONFIRM="   Type YES to continue: "
if /i not "%CONFIRM%"=="YES" (
    echo   Cancelled.
    pause
    exit /b 0
)

REM -ExecutionPolicy Bypass applies to this PowerShell process only; the
REM machine-wide policy is left exactly as it was.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -ExePath "%EXEPATH%"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo   Done. Reboot to enter kiosk mode.
) else (
    echo   [X] Setup failed with exit code %RC% - the machine is NOT in kiosk mode.
)
echo.
pause
exit /b %RC%
