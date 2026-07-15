## 2024-05-24 - Explicit Empty States in Dashboards
**Learning:** When Grafana panels lack data (e.g. probes offline, new deployment), showing a blank/default value confuses users into thinking the service is down or the query failed. Explicitly showing "Sin datos" prevents this ambiguity.
**Action:** Always provide explicit `noValue` configurations for panel field defaults in visualization builders.

## 2024-07-15 - Filterable Categorical Columns & Reusable Panels
**Learning:** Hardcoding column-specific properties like `sortBy` on reusable Grafana panel components severely limits their flexibility and UX. Additionally, explicitly enabling `custom.filterable: true` for categorical state columns (e.g., 'Estado', 'Servicio') significantly improves dashboard UX by allowing users to quickly drill down into specific statuses.
**Action:** Remove hardcoded layout properties from generic panel builders and explicitly enable `custom.filterable` for all categorical columns via overrides.
