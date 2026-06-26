# CX-Radar Product Context

CX-Radar is an automated Quality of Experience (QoE) monitoring solution designed to run continuously on local network probes. It measures, records, and alerts on the performance of key web services (Netflix, YouTube, Microsoft, Disney+, Amazon) from the local network's perspective.

---

## 🎯 Product Goals

1. **Preemptive Alerting & Monitoring**: Detect response latencies, download/upload throughput drop-offs, and service outages before the end-users report them.
2. **Objective Network Performance Data**: Capture concrete indicators (latency in ms, jitter, and transfer rates in Mbps) to facilitate service level agreement (SLA) verification and ISP troubleshooting.
3. **Trend Analysis**: Provide persistent historical records to identify daily/weekly performance degradation patterns.
4. **Zero OS Contamination**: Use isolated, portable binary tools (`node`, `fast-cli`, `yt-dlp`, `curl`) to ensure the host operating system's global files, variables, or system settings remain unchanged.
5. **Cross-Platform Adaptability**: Support modern and legacy environments (Windows, Windows Server 2012 R2, Linux, and macOS) from a single cross-platform code base.

---

## 🚫 Non-Goals & Scope Exclusions

- **High-Throughput Benchmarks**: This tool is designed for synthetic HTTP lane monitoring. Dedicated speed tests (like LibreSpeed or WebPageTest integrations) are kept strictly separate from the active probe lane.
- **Graphical User Configuration**: All configurations are handled via file-based inputs (`config/probe-catalog.json`). No interactive GUI is planned for setting up probe details.
- **Native OS Installers**: System installation relies entirely on native task schedulers (Windows Task Scheduler, systemd, cron, launchd) registered via helper scripts.

---

## 👥 Target Personas

### 1. Network Operations (NetOps) & SREs
* **Needs**: Stable, accurate, and lightweight probes that do not leak memory or exhaust local resources. They need structured raw metrics in a time-series database (InfluxDB) and customizable, clear dashboards (Grafana).
* **Pain Points**: Flaky scripts that crash silently, or complex dependencies that require manual upgrades on dozens of remote machines.

### 2. IT Support / Helpdesk Managers
* **Needs**: Early notification when a major CDN or web service (e.g., Microsoft Office 365, YouTube) starts responding slowly, allowing them to troubleshoot locally before receiving high tickets.
* **Pain Points**: "It feels slow" reports from users without quantitative data to verify if it is an ISP issue, a local Wi-Fi bottleneck, or an outage.

---

## ✨ Core Features

- **Multi-Service Probe Execution**: Continuous checking of latency, jitter, download speeds (using fast-cli for Netflix CDN and yt-dlp for YouTube CDN), and HTTP status codes.
- **Secure Configuration Storage**: Restricts local secrets (.env file) to OS-level secure permissions.
- **Resilient Network Architecture**: Gracefully handles DNS failures, database timeouts, and invalid API endpoints without crashing the probe thread.
- **Self-Maintenance Routine**: Automatically cleans up its temporary files and older logs to prevent disk space exhaustion.
- **Atomic Updater**: Compares local SHA-256 hashes against the central GitHub repository and applies updates atomically.
