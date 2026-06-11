## 2024-05-24 - Avoid Double External Tool Invocations
**Learning:** Found a bottleneck where `yt-dlp.exe` was invoked twice per measurement: once to resolve the direct URL (`Resolve-YtDlpDirectUrl`), and again right after to resolve the host (`Resolve-YtDlpDirectHost` calling `Resolve-YtDlpDirectUrl` internally). External process spawning and network resolution is expensive.
**Action:** Pass already computed expensive values (like `$directMediaUrl`) as parameters to helper functions instead of re-computing them, halving the overhead.
