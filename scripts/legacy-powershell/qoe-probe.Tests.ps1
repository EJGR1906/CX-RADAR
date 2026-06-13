BeforeAll {
    # It appears the user was testing scripts/legacy-powershell/qoe-probe.ps1 because it's where the code actually lives.
    # The reviewer thinks the file is in scripts/qoe-probe.ps1.
    # Let's put the test file in the SAME DIRECTORY as the original script, which is standard practice in powershell modules.

    $scriptPath = "$PSScriptRoot/qoe-probe.ps1"

    # We create a dummy config to allow dot-sourcing without error.
    # This avoids truncating the script!
    $configDir = "$PSScriptRoot/../../config"
    $configPath = "$configDir/probe-catalog.json"
    $createdConfigDir = $false
    $createdConfig = $false

    if (-not (Test-Path $configDir)) {
        New-Item -ItemType Directory -Path $configDir | Out-Null
        $createdConfigDir = $true
    }

    if (-not (Test-Path $configPath)) {
        Set-Content -Path $configPath -Value '{"probeRun": {"logDirectory": "logs"}, "probe": {}, "influx": {}, "targets": []}'
        $createdConfig = $true
    }

    try {
        # By providing a valid fake configuration file and avoiding Execution preferences we can load functions properly
        . $scriptPath -ConfigPath $configPath -SkipInfluxWrite -ErrorAction SilentlyContinue
    } catch {
        # Catch any errors from execution block
    }
}

AfterAll {
    if ($createdConfig) {
        Remove-Item -Path $configPath -Force
    }
    if ($createdConfigDir) {
        Remove-Item -Path $configDir -Force -Recurse
    }
}

Describe "Get-TargetHost" {
    It "Should return an empty string when invalid URL is provided causing [System.Uri] cast to throw" {
        $target = [pscustomobject]@{
            url = 'not a url'
        }
        $result = Get-TargetHost -Target $target
        $result | Should -BeNullOrEmpty
    }
}
