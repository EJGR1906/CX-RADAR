---
name: "qoe_secops_hardening"
description: "Security hardening of the QoE probe, safe credential/token storage with set_influx_token.py, environment variables, rate limiting, and defensive security measures."
---

# QoE SecOps Hardening Skill

Use this skill when managing credentials, configuring tokens, setting environment variables, hardening execution context, or reviewing rate limit / IP reputation risks.

## Key Targets & Context
- **Token Management**: [set_influx_token.py](file:///c:/Users/Eduar/Documents/CX-RADAR/scripts/set_influx_token.py)
- **Hardening Guide**: [docs/security/hardening.md](file:///c:/Users/Eduar/Documents/CX-RADAR/docs/security/hardening.md)

## Credential Hardening Rules
- **No Plaintext Secrets**: Never store the InfluxDB token or API keys directly in files tracked by git.
- **Token Storage**: Use `set_influx_token.py` to write/manage secrets. The probe reads tokens from process environment variables or a restricted `.env` file in the workspace root.
- **Least Privilege**: Ensure the InfluxDB token only has write permission to the specific bucket (`qoe_metrics`) and no administrative or read privileges on the cloud organization unless explicitly needed.

## Network Hardening Rules
- **Rate Limiting / IP Bans**: Since the probe targets streaming endpoints periodically, always maintain random startup jitter and target delay to avoid triggering CDN / target-side abuse detection and IP bans.
