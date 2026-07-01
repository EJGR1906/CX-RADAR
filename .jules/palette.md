## 2024-05-24 - Explicit Empty States in Dashboards
**Learning:** When Grafana panels lack data (e.g. probes offline, new deployment), showing a blank/default value confuses users into thinking the service is down or the query failed. Explicitly showing "Sin datos" prevents this ambiguity.
**Action:** Always provide explicit `noValue` configurations for panel field defaults in visualization builders.
