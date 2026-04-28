# WebPageTest Integration Notes

## Role In This Platform

WebPageTest is the weekly deep-audit lane. It is for browser-level page analysis such as Core Web Vitals, Lighthouse, waterfalls, and render timing.

## Recommended Usage

1. Weekly or release-based audits.
2. A small set of business-critical URLs first.
3. Separate dashboards and alert thresholds from the lightweight curl probe.

## Future Integration Model

Store only summary metrics in InfluxDB under `qoe_page_audit` at first. Keep heavy artifacts such as screenshots, waterfalls, and videos in WebPageTest itself.

## Decision Boundary

Use WebPageTest when the question is:

1. Why is a page slow to load?
2. Did page performance regress this week?
3. What changed in DNS, TCP, TLS, render, or third-party dependencies?

Do not use WebPageTest as a replacement for the 5-minute synthetic lane.