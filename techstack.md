# CX-Radar Technology Stack

This document defines the software stack, external dependencies, system requirements, and programming constraints for the CX-Radar QoE probe.

---

## 💻 Core Runtime & Programming Language

- **Primary Runtime**: **Python 3** (version 3.8 or higher is required).
  - **Constraint**: **Standard Library Only**. No external PyPI packages (`pip install`) are permitted to run the probe. This guarantees lightweight execution and simple deployment across heterogeneous servers.
  - **Legacy OS Fallback**: Python 3.10.x must be used for legacy systems like Windows Server 2012 R2.

- **PowerShell Deprecation**: All legacy `.ps1` code has been removed. No new PowerShell files are permitted in the codebase. All scripting must be completed in Python 3.

---

## 📦 Third-Party Portables

To perform tests that mimic real-user activities, the probe downloads and controls isolated portable dependencies. These are stored under the `/bin` directory and must not require system installation:

| Binary / Tool | Runtime Context | Purpose |
|---|---|---|
| **Node.js** | Portable binary (v20 standard, v16 for WS 2012 R2) | Runs the Netflix speed measurement package. |
| **`fast-cli`** | Packaged Node.js CLI script | Performs speed tests against Fast.com/Netflix CDNs. |
| **`yt-dlp`** | Portable compiled binary | Downloads video chunks from YouTube to measure real throughput. |
| **`curl`** | Portable system binary | Performs low-overhead HTTP transactions. |

---

## ☁️ External Services & Ingestion Flow

```
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  Python 3 Probe  │ ───> │  InfluxDB Cloud  │ ───> │  Grafana Cloud   │
│  (Local Server)  │      │ (Time-Series DB) │      │   (Dashboard)    │
└──────────────────┘      └──────────────────┘      └──────────────────┘
```

1. **Ingestion Port**: InfluxDB v2 Line Protocol API endpoint over HTTPS.
2. **Database Engine**: InfluxDB Cloud (Bucket-oriented storage).
3. **Visualization Engine**: Grafana Cloud.
4. **Query Language**: Flux (for loading metrics from InfluxDB).

---

## ⚙️ Configuration Management

- **`config/probe-catalog.json`**:
  - Defines probe location properties (`probeId`, `site`, `environment`, `isp`).
  - Contains service catalog list (`targets`) with metadata, targets endpoints, and test parameters.
- **`.env` (Local Secrets)**:
  - Stored in the project root with OS-restricted access permissions.
  - Contains InfluxDB token (`INFLUX_TOKEN`). Must not be version-controlled.

---

## 📊 Monitoring Metrics Schema

Metrics are sent to InfluxDB under three measurements:
- **`qoe_http_check`**: Latency, availability, and response codes for regular CDN/endpoints.
- **`qoe_real_metrics`**: Download/upload speeds, jitter, and connection quality for Netflix and YouTube.
- **`qoe_probe_run`**: Internal metadata about the probe execution itself (run duration, errors).

---

## 🔄 Local Validation Workflow

Before checking in changes, developers must validate their code using the following execution order:

1. **Environment Lint & Verification**:
   ```bash
   python scripts/validate_qoe_probe.py
   ```
2. **Dry Run (No Network writes)**:
   ```bash
   python scripts/qoe_probe.py --skip-influx-write
   ```
3. **Execution with Ingress**:
   ```bash
   python scripts/qoe_probe.py
   ```
4. **QA Smoke & Resilience Testing**:
   ```bash
   python scripts/run_qoe_certification.py --run-resilience-checks
   ```
