## 2024-05-24 - [Command Injection via PowerShell String Interpolation]
**Vulnerability:** PowerShell scripts constructed using Python f-strings injected user-controlled paths and descriptions directly into the script execution block.
**Learning:** `shutil.which` does not prevent path manipulation vulnerabilities on its own since it relies on the environment PATH, and injecting strings into PowerShell scripts is prone to command injection.
**Prevention:** Pass external variables safely to PowerShell by embedding them into `os.environ` and referencing them within the PowerShell script using `$env:VARIABLE_NAME`.
