## 2026-06-27 - [Command Injection via String Interpolation in PowerShell]
**Vulnerability:** Found a shell injection vulnerability in `scripts/set_influx_token.py` where a configuration-driven variable name was interpolated directly into a PowerShell command using Python f-strings.
**Learning:** String interpolation for variables into `subprocess.run()` shell commands allows malicious environment variable inputs to escape the payload and execute arbitrary powershell commands.
**Prevention:** Pass data into subprocess shell scripts securely by utilizing the `env` parameter, passing values through environment variables, and referencing them native to the shell script (e.g., `$env:CX_RADAR_VAR_NAME`).
