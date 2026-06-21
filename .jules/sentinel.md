## 2024-06-12 - PowerShell Command Injection in Probe Cleanup
**Vulnerability:** A critical PowerShell command injection vulnerability was present in the `kill_dangling_chrome` function of the Python probe script (`scripts/qoe_probe.py`). The script used an f-string to interpolate a user-controllable path (`puppeteer_cache_dir` derived from `config/probe-catalog.json`) directly into a PowerShell command block.
**Learning:** String interpolation in shell commands, especially complex ones like PowerShell pipelines (`Get-Process ... | Where-Object { $_.Path.StartsWith('{cache_path_str}') } | Stop-Process`), is highly dangerous. Even if the input source (like a config file) is currently trusted, it creates a fragile defense-in-depth posture.
**Prevention:** Never use string formatting or concatenation to inject variables into shell commands. Always pass data securely through environment variables (e.g., passing the path in `$env:TARGET_CACHE_PATH` and accessing it inside the PowerShell script block) or via parameterized arguments when supported.
## 2024-05-20 - Token Exposure in OS Process Lists
**Vulnerability:** InfluxDB token exposure in OS process lists via `setx` arguments (Windows) and `--token` arguments during provisioning.
**Learning:** Using command-line arguments to pass sensitive tokens exposes them to any user who can run `ps` or view process lists (e.g., Task Manager).
**Prevention:** Pass sensitive tokens using environment variables specifically scoped for the provisioning task (like `CX_RADAR_PROVISIONING_TOKEN`), and use OS-level APIs (like PowerShell `[Environment]::SetEnvironmentVariable`) that support environment variable expansion within the script/process rather than as process arguments.
## 2024-06-16 - Path Traversal via Unsafe Archive Extraction
**Vulnerability:** A path traversal vulnerability existed in `scripts/setup_portable.py` due to the use of `zipfile.extractall()` and `tarfile.extractall()` without validating whether the extracted files remain within the intended directory. This could potentially allow arbitrary file write on the host if a malicious or compromised archive (like a manipulated Node.js tarball) is downloaded and unpacked.
**Learning:** Functions like `extractall()` blindly trust the file paths stored within the archive. Python's built-in extraction tools do not perform comprehensive protection against `../` path components traversing outside the target destination folder.
**Prevention:** Always manually iterate over archive contents (e.g. `zf.infolist()` or `tf.getmembers()`), resolve the absolute destination path for each member, and verify it starts with the absolute path of the intended extraction directory using `os.path.commonpath()` before calling `extract()`.
## 2024-06-16 - Inline Secret in Documentation/Crontab
**Vulnerability:** An example crontab file (`orchestration/crontab-example.txt`) contained an inline export of the `INFLUXDB_TOKEN` secret.
**Learning:** Including inline secrets or instructions to "set it inline" in documentation or example files encourages bad security practices that can lead to secrets being exposed in OS logs, process listings, or accidentally committed.
**Prevention:** Always ensure documentation and example files direct users to use secure credential management (like `.env` files or secure vaults) rather than inline exports or hardcoded placeholders in command lines.

## 2024-06-21 - Broken Authentication Due to Incomplete Security Fix
**Vulnerability:** While removing hardcoded token generation from `register_qoe_task.py`, the systemd environment was not given an alternative credential source, causing dynamic task deployments to fail authentication.
**Learning:** Removing an exposed secret from a template without substituting it with a secure runtime alternative (like `EnvironmentFile`) causes operational regressions. Removing security risks must not break core functionality.
**Prevention:** When removing hardcoded tokens from dynamic configuration templates (e.g., systemd service files), ensure a secure alternative is provided (such as adding `EnvironmentFile={script_path.parent.parent}/.env` for systemd) to prevent authentication regressions in generated tasks.
## 2026-06-21 - [Command Injection via f-strings in subprocess.run(powershell)]
**Vulnerability:** PowerShell execution commands built dynamically with Python f-strings exposed the scripts to command injection.
**Learning:** Using `$env:VAR_NAME` syntax inside the PowerShell block and passing arguments securely via the `env` dictionary to `subprocess.run()` prevents arbitrary command execution from dynamically injected string content.
**Prevention:** Never use f-strings to inject user-provided or dynamically derived variables into PowerShell scripts executed via `subprocess.run()`. Always map them to process environment variables (`env=env`) and reference them using `$env:VAR_NAME` inside the script.
