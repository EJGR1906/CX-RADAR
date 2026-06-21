1. **Identify Performance Improvement**: The performance optimization is to move the `re.compile` declarations from `convert_from_probe_log` in `scripts/run_qoe_certification.py` to the module level.
2. **Review Code**: Inspect `scripts/run_qoe_certification.py` to move `http_success_rx`, `speed_success_rx`, `speed_fail_rx`, and `summary_rx` to the global scope to avoid recompiling these regular expressions every time `convert_from_probe_log` is called.
3. **Modify Code**: Edit `scripts/run_qoe_certification.py` to move the `re.compile` declarations.
4. **Pre-commit Checks**: Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.
5. **Submit PR**: Submit the changes with a PR describing the performance improvement following the Bolt formatting constraints.
