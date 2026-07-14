## 2024-05-24 - Explicit Empty States in Dashboards
**Learning:** When Grafana panels lack data (e.g. probes offline, new deployment), showing a blank/default value confuses users into thinking the service is down or the query failed. Explicitly showing "Sin datos" prevents this ambiguity.
**Action:** Always provide explicit `noValue` configurations for panel field defaults in visualization builders.

## 2024-07-14 - Flexible Table Panels and Categorical Filters
**Learning:** Hardcoding column-specific properties like `sortBy` on reusable panel components reduces dashboard flexibility and can cause bugs when columns don't exist. Additionally, explicitly enabling filterability for categorical state columns significantly improves dashboard navigation.
**Action:** Avoid hardcoding specific column names in reusable components and actively enable `custom.filterable` for relevant categorical columns (like 'Estado', 'Servicio').
