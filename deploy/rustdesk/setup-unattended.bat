@echo off
setlocal enabledelayedexpansion
REM ============================================================================
REM  RustDesk unattended access for a KKMI kiosk.
REM
REM  Right-click this file -> "Run as administrator".
REM
REM  A .bat, not the .ps1: PowerShell's default ExecutionPolicy on Windows 10
REM  refuses to run unsigned .ps1 files, which turns a two-minute job into a
REM  policy fight on a machine somebody has to physically walk to. cmd has no
REM  such gate.
REM
REM  What it fixes: RustDesk defaults to "Accept sessions via click", so every
REM  connection waits for somebody at the kiosk to press Accept — and a file
REM  transfer opens a SECOND session, so it asks twice. Nobody is standing at a
REM  lobby kiosk.
REM
REM  Three things are needed and none of them works alone:
REM    1. RustDesk INSTALLED (not portable) - only that registers the Windows
REM       service, and only the service survives logout / lock screen / UAC.
REM    2. A PERMANENT password - the default one-time password rotates and is
REM       shown on screen, which is useless when nobody is there to read it.
REM    3. approve-mode=password - makes the password itself the approval, which
REM       is what removes BOTH prompts (a file transfer is just another session).
REM
REM  Usage:
REM    setup-unattended.bat "YourStrongPassword"
REM    setup-unattended.bat "YourStrongPassword" "C:\path\to\rustdesk-x.y.z-x86_64.exe"
REM ============================================================================

set "PASSWORD=%~1"
set "INSTALLER=%~2"
set "RD=%ProgramFiles%\RustDesk\rustdesk.exe"

REM ---- admin check -----------------------------------------------------------
REM  --password and --option silently do nothing without admin (RustDesk checks
REM  is_installed() && is_root()), so a non-elevated run looks like it worked
REM  and changes nothing. Fail loudly instead.
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [X] Administrator required.
    echo       Right-click this file and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

if "%PASSWORD%"=="" (
    echo.
    echo   Usage: setup-unattended.bat "YourStrongPassword" ["path\to\installer.exe"]
    echo.
    pause
    exit /b 1
)

REM ---- 1. install if missing -------------------------------------------------
if not exist "%RD%" (
    if exist "%ProgramFiles(x86)%\RustDesk\rustdesk.exe" (
        set "RD=%ProgramFiles(x86)%\RustDesk\rustdesk.exe"
    )
)

if not exist "%RD%" (
    if "%INSTALLER%"=="" (
        echo.
        echo   [X] RustDesk is not installed and no installer path was given.
        echo       Download it from https://rustdesk.com/ then run:
        echo         setup-unattended.bat "%PASSWORD%" "C:\path\to\rustdesk-x.y.z-x86_64.exe"
        echo.
        pause
        exit /b 1
    )
    if not exist "%INSTALLER%" (
        echo   [X] Installer not found: %INSTALLER%
        pause
        exit /b 1
    )
    echo   [1/4] Installing RustDesk as a service...
    REM --silent-install installs AND registers the service - the same thing as
    REM ticking "Run as service" in the interactive installer.
    "%INSTALLER%" --silent-install
    REM The installer returns before the files land.
    for /l %%i in (1,1,30) do (
        if exist "%ProgramFiles%\RustDesk\rustdesk.exe" goto :installed
        timeout /t 1 /nobreak >nul
    )
:installed
    set "RD=%ProgramFiles%\RustDesk\rustdesk.exe"
    if not exist "!RD!" (
        echo   [X] Install finished but rustdesk.exe was not found.
        pause
        exit /b 1
    )
) else (
    echo   [1/4] RustDesk already installed: %RD%
)

REM ---- 2. service ------------------------------------------------------------
echo   [2/4] Ensuring the service is running and set to start at boot...
sc query RustDesk >nul 2>&1
if errorlevel 1 "%RD%" --install-service
sc config RustDesk start= auto >nul 2>&1
sc start RustDesk >nul 2>&1

REM ---- 3. password + approval mode -------------------------------------------
echo   [3/4] Setting the permanent password and approval mode...
REM Password first, so the machine is never briefly in "accept by password"
REM with no password set.
"%RD%" --password "%PASSWORD%"
"%RD%" --option verification-method use-permanent-password
"%RD%" --option approve-mode password
"%RD%" --option enable-file-transfer Y
REM Stops somebody at the kiosk changing the password and locking support out.
REM Note this also means it cannot be rotated locally - re-run this file.
"%RD%" --option disable-change-permanent-password Y

REM ---- 4. verify -------------------------------------------------------------
echo   [4/4] Verifying...
echo.
for /f "delims=" %%a in ('"%RD%" --option verification-method') do set "V_METHOD=%%a"
for /f "delims=" %%a in ('"%RD%" --option approve-mode')        do set "V_APPROVE=%%a"
for /f "delims=" %%a in ('"%RD%" --option enable-file-transfer') do set "V_FILES=%%a"
for /f "delims=" %%a in ('"%RD%" --get-id')                      do set "V_ID=%%a"

echo     verification-method  = !V_METHOD!     (expected: use-permanent-password)
echo     approve-mode         = !V_APPROVE!               (expected: password)
echo     enable-file-transfer = !V_FILES!                      (expected: Y)
echo.
echo     RustDesk ID          = !V_ID!
echo.

if /i not "!V_APPROVE!"=="password" (
    echo   [!] approve-mode did not stick. Usual cause: a portable rustdesk.exe is
    echo       running, so the CLI talked to the wrong instance. Close it and retry.
    echo.
    pause
    exit /b 1
)

echo   Done. Connect with the ID above and your password - the kiosk will not
echo   prompt, for screen control or file transfer.
echo.
pause
