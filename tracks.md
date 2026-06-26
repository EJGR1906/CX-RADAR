# CX-Radar Work Tracks

This document records completed development phases, active work streams, and upcoming project roadmap tasks.

---

## 🟢 Active Track: Conductor Initialization
* **Objective**: Initialize Conductor context-driven development.
* **Tasks**:
  - [x] Gather project requirements and constraints from `README.md` and `AGENTS.md`.
  - [x] Create product goals document (`product.md`).
  - [x] Create technical stack specifications (`techstack.md`).
  - [x] Set up work tracking log (`tracks.md`).
  - [x] Perform validation checks to verify local environment.

---

## 🏆 Completed Tracks

### 1. PowerShell to Python 3 Migration
* **Objective**: Migrate the legacy Windows-only PowerShell probe scripts to a unified cross-platform Python 3 implementation.
* **Details**:
  - Deleted legacy `.ps1` command scripts and tests.
  - Implemented portable tool manager (`scripts/setup_portable.py`) downloading compatible Node.js, `fast-cli`, and `yt-dlp` executables.
  - Ported probe logic (`scripts/qoe_probe.py`) to Python 3 using standard library modules only.
  - Standardized InfluxDB line-protocol generation and writing.

### 2. Probe Script Security Hardening
* **Objective**: Remediate potential shell injection vulnerabilities in script runtime executions.
* **Details**:
  - Remediated command injection vulnerability in Puppeteer cache cleanup functions.
  - Refactored all subprocess invocation logic to pass arguments securely as lists, preventing command line string splitting vulnerabilities.

---

## 📋 Roadmap & Backlog

### 1. Throughput Benchmarks Integration
* **Objective**: Add dedicated network throughput measurements using LibreSpeed or WebPageTest.
* **Constraint**: Must remain separated from the main synthetic HTTP lane (`qoe_http_check`) to prevent overloading system queues.

### 2. Grafana Dashboard Alert Tuning
* **Objective**: Optimize Flux alert query configurations to avoid false-positive notifications due to isolated probe offline timeouts.
* **Tasks**:
  - Tune jitter alert ranges.
  - Introduce sliding-window average parameters to smooth short-term latency spikes.
