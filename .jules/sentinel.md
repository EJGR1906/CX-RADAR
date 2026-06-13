## 2024-06-12 - PowerShell Command Injection in Probe Cleanup
**Vulnerability:** A critical PowerShell command injection vulnerability was present in the `kill_dangling_chrome` function of the Python probe script (`scripts/qoe_probe.py`). The script used an f-string to interpolate a user-controllable path (`puppeteer_cache_dir` derived from `config/probe-catalog.json`) directly into a PowerShell command block.
**Learning:** String interpolation in shell commands, especially complex ones like PowerShell pipelines (`Get-Process ... | Where-Object { $_.Path.StartsWith('{cache_path_str}') } | Stop-Process`), is highly dangerous. Even if the input source (like a config file) is currently trusted, it creates a fragile defense-in-depth posture.
**Prevention:** Never use string formatting or concatenation to inject variables into shell commands. Always pass data securely through environment variables (e.g., passing the path in `$env:TARGET_CACHE_PATH` and accessing it inside the PowerShell script block) or via parameterized arguments when supported.

## 2024-06-13 - Unverified TLS Download in QoE Probe Updater
**Vulnerability:** The auto-updater script (`scripts/update_qoe_probe.py`) contained a bypass for TLS certificate validation (`ssl.CERT_NONE` and `curl -k`), allowing potential Man-in-the-Middle (MitM) attacks.
**Learning:** Hardcoded logic or optional flags to bypass SSL/TLS verification introduce significant risk, especially when downloading executable scripts that will be run automatically.
**Prevention:** Always enforce strict TLS verification for all external network requests, particularly when downloading code or executing remote updates. Avoid implementing optional "insecure" flags that users might misuse or leave enabled.
