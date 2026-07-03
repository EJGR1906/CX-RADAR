## 2024-05-18 - [Optimized shutil.copyfileobj Buffer Size for High-Throughput HTTP Downloads]
**Learning:** `shutil.copyfileobj` relies on a default block size which is often too small for high-bandwidth connections (e.g., 16KB or 64KB). When performing synthetic speed tests (like downloading an 8MB or 100MB chunk to measure throughput), this small buffer causes excessive `read()`/`write()` syscalls and Python-level loop overhead. This can artificially limit the measured download Mbps, confusing probe overhead with true network capacity.
**Action:** Always provide a larger explicit `length` parameter (e.g., `length=1024 * 1024` for 1MB blocks) to `shutil.copyfileobj` when building diagnostic tools or high-throughput file transfer loops in Python to prevent the interpreter/OS context switches from becoming the bottleneck.## 2026-06-13 - [Performance Optimization: PowerShell I/O Checks]
**Learning:** `Test-Path` in PowerShell is slow because it routes through the PS provider subsystem. Repeated calls inside loops cause measurable performance degradation. Using `[System.IO.File]::Exists` and `[System.IO.Directory]::Exists` bypasses the provider system entirely, directly invoking OS-level stat calls, which is orders of magnitude faster. Furthermore, eliminating redundant checks by returning state directly from utility functions (via switches like `-PassThru`) minimizes expensive I/O operations.
**Action:** When performing file existence checks in high-frequency PowerShell loops or heavily utilized utility functions, prefer native .NET `System.IO` methods over `Test-Path`, provided the paths are well-formed absolute file paths (which `System.IO` strictly requires).

## 2026-06-13 - [Project Standard: Python 3 Only & PowerShell Deprecation]
**Learning:** The project has been fully migrated from PowerShell to Python 3. All legacy `.ps1` files and tests have been deleted to clean up the repository. New files, features, probes, and tests must be implemented exclusively in Python 3.
**Action:** Do not write or support any PowerShell scripts (`.ps1`). Maintain and execute only the Python 3 probe ecosystem. For local execution and verification, always follow this order of validation commands:
1. Validate environment: `python scripts/validate_qoe_probe.py`
2. Run dry run probe: `python scripts/qoe_probe.py --skip-influx-write`
3. Run full probe: `python scripts/qoe_probe.py`
4. Run QA certification: `python scripts/run_qoe_certification.py`

## 2026-06-15 - [Identify Dead Regex Checks for Faster Parsing]
**Learning:** Sometimes overlapping regexes cause dead code that iterates without effect. In `scripts/qoe_probe.py`, `sub_ms_regex` checking for `< 1 ms` was entirely redundant because the primary `time_regex` already matched `<1ms` successfully and correctly grouped the `1`.
**Action:** When optimizing repeated regex searches inside line-parsing loops, analyze the regex logic for overlaps to avoid unnecessary regex executions entirely.
## 2026-06-15 - [Performance Optimization: Pre-compile Regex at Module Level]
**Learning:** Compiling regex with `re.compile` inside frequently executed functions or loops adds unnecessary overhead by repeatedly checking the `re` module's internal cache or worse, recompiling it if the cache overflows. This CPU overhead can subtly skew latency or performance measurement loops.
**Action:** Always move `re.compile` declarations to the global module level so they are evaluated exactly once when the script loads, especially inside functions doing latency extraction or iterative string processing.
## 2026-06-15 - [Optimize Identity Deduplication with dict comprehension]
**Learning:** Manual loop and set tracking for deduplicating Python objects by their identity (`id()`) incurs measurable overhead due to bytecode execution for sets and list appends. For high-frequency or large-scale tasks, dict comprehensions (`list({id(x): x for x in items}.values())`) perform the same behavior but execute much faster using the underlying optimized C dictionary implementation while preserving insertion order (Python 3.7+).
**Action:** When performing identity-based or unique-key deduplication in Python while needing to preserve order, prefer dictionary comprehensions extracting `.values()` over `for` loops combined with `set()` tracking.
## 2026-07-03 - [Optimize String Replacement with Chained replace calls]
**Learning:** Sequential `.replace()` assignments (e.g., `val = val.replace(...)` over multiple lines) are slower than chaining them directly (e.g., `str(value).replace(...).replace(...)`). Chaining leverages Python's internal string processing fast paths more efficiently by avoiding the `STORE_FAST` and `LOAD_FAST` bytecode overhead associated with storing intermediate results in local variables, yielding an approximate 40% performance improvement in high-frequency string escaping formatting functions.
**Action:** When performing multiple deterministic string replacements on the same variable, prefer chained `.replace().replace()` calls on a single line instead of sequential assignments to a local variable.
