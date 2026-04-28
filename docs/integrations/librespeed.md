# LibreSpeed Integration Notes

## Role In This Platform

LibreSpeed is not part of the 5-minute synthetic probe loop. Its role is to measure internal path quality and throughput against your own controlled infrastructure.

## Recommended Usage

1. On-demand diagnostics for support and troubleshooting.
2. Low-frequency scheduled tests, not every 5 minutes.
3. Separate dashboards from the synthetic HTTP lane.

## Future Integration Model

If LibreSpeed results are normalized into InfluxDB later, map them to `qoe_speed_test` and keep those points separate from `qoe_http_check`.

## Decision Boundary

Use LibreSpeed when the question is:

1. Is the local access path or ISP capacity degraded?
2. Is Wi-Fi or branch connectivity the bottleneck?

Do not use LibreSpeed as a substitute for service reachability or browser audit measurements.