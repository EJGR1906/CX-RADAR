## 2024-06-19 - [Fix Token Exposure in Process List]
**Vulnerability:** The InfluxDB API token was being passed as a command-line argument (`--token`) when `install.py` called `set_influx_token.py` via `subprocess.run()`.
**Learning:** Passing secrets as command-line arguments makes them visible to all users on the system via process listing tools (e.g., `ps`, `top`) and can inadvertently leak them into application logs (e.g., when the command string is printed).
**Prevention:** Use environment variables (e.g., `CX_RADAR_PROVISIONING_TOKEN`) or secure file passing mechanisms to transfer secrets between scripts. When using `subprocess.run()`, use a custom `env` dictionary to inject secrets instead of command-line arguments.
