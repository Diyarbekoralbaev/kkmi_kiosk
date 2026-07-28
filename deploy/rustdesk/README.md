# RustDesk unattended access on a kiosk

A kiosk in a lobby has nobody standing at it. RustDesk's default —
"Accept sessions via click" — waits for someone to press Accept, so every
connection times out. File transfer prompts a second time because it opens a
separate session.

Three things have to be true, and any one alone is not enough:

| | Why |
|---|---|
| RustDesk **installed**, not portable | Only an installed copy registers the Windows service, and only the service survives logout, the lock screen and UAC elevation. A portable exe drops the session the moment the desktop switches. |
| **Permanent password** set | The default one-time password rotates and is displayed on screen — useless when nobody is there to read it. |
| `approve-mode = password` | Makes a correct password the approval. This is what removes both prompts: a file transfer is just another session through the same gate. |

## Usage

From an **elevated** PowerShell on the kiosk:

```powershell
# First time (RustDesk not yet installed)
.\setup-unattended.ps1 -Password 'a-long-passphrase' -Installer .\rustdesk-1.4.4-x86_64.exe

# Already installed
.\setup-unattended.ps1 -Password 'a-long-passphrase'

# Look but don't touch: control allowed, file transfer blocked
.\setup-unattended.ps1 -Password 'a-long-passphrase' -AllowFileTransfer $false
```

The script prints the RustDesk ID and verifies each option actually stuck.

## What it sets

```
rustdesk.exe --password <pw>
rustdesk.exe --option verification-method use-permanent-password
rustdesk.exe --option approve-mode password
rustdesk.exe --option enable-file-transfer Y
rustdesk.exe --option disable-change-permanent-password Y
```

`--password` and `--option` silently do nothing unless RustDesk is installed
**and** the caller is an administrator — see `is_installed() && is_root()` in
[`src/core_main.rs`](https://github.com/rustdesk/rustdesk/blob/master/src/core_main.rs).
That is the usual reason a manual attempt appears to succeed but changes
nothing.

Accepted values, from
[`flutter/lib/consts.dart`](https://github.com/rustdesk/rustdesk/blob/master/flutter/lib/consts.dart)
and [`src/ui/index.tis`](https://github.com/rustdesk/rustdesk/blob/master/src/ui/index.tis):

- `verification-method` — `use-permanent-password` | `use-temporary-password`
- `approve-mode` — `password` | `click` | *(empty = both)*

## Security

This deliberately turns a kiosk into a machine anyone with the ID and password
can drive, unattended, including pulling files off it. RustDesk IDs are short
and enumerable, so **the password is the entire defence**:

- long random passphrase, not a word — the script enforces 12 characters minimum
  but that is a floor, not a recommendation;
- a **different password per kiosk**, so one leak is one machine;
- store them with the rest of the deployment credentials, never in this repo.

`disable-change-permanent-password Y` stops the password being changed from the
kiosk's own UI — set it so a curious visitor cannot lock support out, and
remember it also means you cannot rotate the password locally. Rotate by
re-running this script.

If the kiosks sit on a network you control, restricting outbound RustDesk to
your own relay/ID server is a much stronger control than any password. That is
a separate piece of work.
