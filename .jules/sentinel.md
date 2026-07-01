## 2024-06-22 - Missing Token Substitution in Sentinel Task
**Vulnerability:** Removal of InfluxDB token logic without secure fallback created functional failure
**Learning:** Hardcoded token vulnerabilities inside config templates (like macOS launchd `plist` or systemd `.service`) cannot simply be deleted; there must be a seamless handoff to a secure environment (e.g. `.env` file lookup or secure `Keychain` access) within the launched process.
**Prevention:** Verify whether the process reading the config or being executed has native access to the required environment or secret before stripping it from its launcher.
