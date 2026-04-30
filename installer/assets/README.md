# Installer Assets

Place optional third-party runtime assets here before publishing the bootstrapper EXE.

## Supported Asset

- `ookla-speedtest\speedtest.exe`

If `installer\assets\ookla-speedtest\speedtest.exe` exists at publish time, the WinExe project copies it into `bootstrap-assets\tools\ookla-speedtest\speedtest.exe` so the operator bundle can seed the CLI without relying on PATH or a pre-existing local installation.

Do not commit vendor binaries or secrets unless you have an explicit approval and redistribution path.