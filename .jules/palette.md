## 2024-05-24 - Explicit Empty States in Dashboards
**Learning:** When Grafana panels lack data (e.g. probes offline, new deployment), showing a blank/default value confuses users into thinking the service is down or the query failed. Explicitly showing "Sin datos" prevents this ambiguity.
**Action:** Always provide explicit `noValue` configurations for panel field defaults in visualization builders.

## 2026-07-12 - Reusable Table Columns & Filtering
**Learning:** Hardcoding column names (like 'Sitio') in reusable table components breaks UX on tables without those columns. Additionally, adding `custom.filterable` to categorical columns (like 'Estado' or 'Servicio') significantly improves troubleshooting workflows.
**Action:** Pass dynamic sorting options to reusable table components and explicitly enable filtering for categorical state columns.
