## 2024-06-12 - PowerShell Command Injection in Probe Cleanup
**Vulnerability:** A critical PowerShell command injection vulnerability was present in the `kill_dangling_chrome` function of the Python probe script (`scripts/qoe_probe.py`). The script used an f-string to interpolate a user-controllable path (`puppeteer_cache_dir` derived from `config/probe-catalog.json`) directly into a PowerShell command block.
**Learning:** String interpolation in shell commands, especially complex ones like PowerShell pipelines (`Get-Process ... | Where-Object { $_.Path.StartsWith('{cache_path_str}') } | Stop-Process`), is highly dangerous. Even if the input source (like a config file) is currently trusted, it creates a fragile defense-in-depth posture.
**Prevention:** Never use string formatting or concatenation to inject variables into shell commands. Always pass data securely through environment variables (e.g., passing the path in `$env:TARGET_CACHE_PATH` and accessing it inside the PowerShell script block) or via parameterized arguments when supported.
## 2024-05-20 - Token Exposure in OS Process Lists
**Vulnerability:** InfluxDB token exposure in OS process lists via `setx` arguments (Windows) and `--token` arguments during provisioning.
**Learning:** Using command-line arguments to pass sensitive tokens exposes them to any user who can run `ps` or view process lists (e.g., Task Manager).
**Prevention:** Pass sensitive tokens using environment variables specifically scoped for the provisioning task (like `CX_RADAR_PROVISIONING_TOKEN`), and use OS-level APIs (like PowerShell `[Environment]::SetEnvironmentVariable`) that support environment variable expansion within the script/process rather than as process arguments.
## 2024-06-16 - Inline Secret in Documentation/Crontab
**Vulnerability:** An example crontab file (`orchestration/crontab-example.txt`) contained an inline export of the `INFLUXDB_TOKEN` secret.
**Learning:** Including inline secrets or instructions to "set it inline" in documentation or example files encourages bad security practices that can lead to secrets being exposed in OS logs, process listings, or accidentally committed.
**Prevention:** Always ensure documentation and example files direct users to use secure credential management (like `.env` files or secure vaults) rather than inline exports or hardcoded placeholders in command lines.
