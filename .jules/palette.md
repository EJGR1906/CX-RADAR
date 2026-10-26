## 2024-05-24 - Explicit Empty States in Dashboards
**Learning:** When Grafana panels lack data (e.g. probes offline, new deployment), showing a blank/default value confuses users into thinking the service is down or the query failed. Explicitly showing "Sin datos" prevents this ambiguity.
**Action:** Always provide explicit `noValue` configurations for panel field defaults in visualization builders.

## 2024-07-13 - Dashboard Table Filters and Sort
**Learning:** Categorical state columns (e.g. 'Estado', 'Servicio') in Grafana tables can be difficult to use when there are many rows if they are not filterable. Also, hardcoding `sortBy` on reusable panel components restricts flexibility across different dashboards.
**Action:** Always explicitly enable `custom.filterable: true` for categorical state columns, and avoid hardcoding column-specific properties like `sortBy` on reusable panel components.
