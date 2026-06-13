Describe "Get-RequiredConfigIssues" {
    BeforeAll {
        $env:SystemRoot = "/dummy"

        $scriptContent = [System.IO.File]::ReadAllText("/app/scripts/legacy-powershell/validate-qoe-probe.ps1")
        $parsedScript = [System.Management.Automation.Language.Parser]::ParseInput($scriptContent, [ref]$null, [ref]$null)
        $functions = $parsedScript.FindAll({ param($ast) $ast -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)
        foreach ($func in $functions) {
            Invoke-Expression $func.Extent.Text
        }

        # Mocks for tests using native powershell features rather than Pester Mocking module which sometimes has issues with dynamic scope
        $global:speedTargetFallbackMockResult = $true
        $global:uploadMeasurementMethodMockResult = 'none'
        $global:uploadUrlMeasurementMockResult = $true

        # Override the functions we just loaded
        function Test-SpeedTargetFallbackReady { param($Target) return $global:speedTargetFallbackMockResult }
        function Get-UploadMeasurementMethod { param($Target, $ProbeRun)
            if ($null -ne $Target.uploadMethodMock) { return $Target.uploadMethodMock }
            return $global:uploadMeasurementMethodMockResult
        }
        function Test-UploadUrlMeasurementReady { param($Target) return $global:uploadUrlMeasurementMockResult }
    }

    BeforeEach {
        $global:speedTargetFallbackMockResult = $true
        $global:uploadMeasurementMethodMockResult = 'none'
        $global:uploadUrlMeasurementMockResult = $true
    }

    It "returns 0 issues for a valid configuration" {
        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "test-probe" }
            influx = [pscustomobject]@{
                baseUrl = "http://localhost"
                bucket = "test-bucket"
                tokenEnvVar = "INFLUX_TOKEN"
            }
            targets = @(
                [pscustomobject]@{
                    enabled = $true
                    service = "test-svc"
                    endpointName = "test-ep"
                    type = "http"
                    url = "http://test"
                }
            )
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues.Count | Should -Be 0
    }

    It "requires probe.probeId" {
        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "" }
            influx = [pscustomobject]@{ baseUrl = "test"; bucket = "test"; tokenEnvVar = "test" }
            targets = @( [pscustomobject]@{ enabled = $true; service = "test"; endpointName = "test"; type = "http"; url = "http" } )
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues | Should -Contain "probe.probeId is required."
    }

    It "requires influx.baseUrl, influx.bucket, and influx.tokenEnvVar" {
        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "test" }
            influx = [pscustomobject]@{ baseUrl = ""; bucket = ""; tokenEnvVar = "" }
            targets = @( [pscustomobject]@{ enabled = $true; service = "test"; endpointName = "test"; type = "http"; url = "http" } )
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues | Should -Contain "influx.baseUrl is required."
        $issues | Should -Contain "influx.bucket is required."
        $issues | Should -Contain "influx.tokenEnvVar is required."
    }

    It "requires at least one enabled target" {
        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "test" }
            influx = [pscustomobject]@{ baseUrl = "test"; bucket = "test"; tokenEnvVar = "test" }
            targets = @()
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues | Should -Contain "At least one enabled target is required."
    }

    It "requires service and endpointName for enabled targets" {
        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "test" }
            influx = [pscustomobject]@{ baseUrl = "test"; bucket = "test"; tokenEnvVar = "test" }
            targets = @(
                [pscustomobject]@{ enabled = $true; service = ""; endpointName = "test" },
                [pscustomobject]@{ enabled = $true; service = "test"; endpointName = "" }
            )
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues | Should -Contain "Enabled target is missing service."
        $issues | Should -Contain "Target 'test' is enabled but has no endpointName."
    }

    It "requires URL for HTTP targets" {
        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "test" }
            influx = [pscustomobject]@{ baseUrl = "test"; bucket = "test"; tokenEnvVar = "test" }
            targets = @(
                [pscustomobject]@{ enabled = $true; service = "test"; endpointName = "test"; type = "http"; url = "" }
            )
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues | Should -Contain "HTTP target 'test/test' is enabled but has no URL."
    }

    It "requires speedTestMethod for speedtest targets" {
        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "test" }
            influx = [pscustomobject]@{ baseUrl = "test"; bucket = "test"; tokenEnvVar = "test" }
            targets = @(
                [pscustomobject]@{ enabled = $true; service = "test"; endpointName = "test"; type = "speedtest"; speedTestMethod = "" }
            )
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues | Should -Contain "Speed-test target 'test/test' is missing speedTestMethod."
    }

    It "rejects unsupported speedTestMethod" {
        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "test" }
            influx = [pscustomobject]@{ baseUrl = "test"; bucket = "test"; tokenEnvVar = "test" }
            targets = @(
                [pscustomobject]@{ enabled = $true; service = "test"; endpointName = "test"; type = "speedtest"; speedTestMethod = "magic" }
            )
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues | Should -Contain "Target 'test/test' uses unsupported speedTestMethod 'magic'."
    }

    It "validates specific requirements for different speedTestMethods" {
        $global:speedTargetFallbackMockResult = $false

        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "test" }
            influx = [pscustomobject]@{ baseUrl = "test"; bucket = "test"; tokenEnvVar = "test" }
            targets = @(
                [pscustomobject]@{ enabled = $true; service = "yt"; endpointName = "yt"; type = "speedtest"; speedTestMethod = "yt-dlp"; videoUrl = ""; url = "" },
                [pscustomobject]@{ enabled = $true; service = "nq"; endpointName = "nq"; type = "speedtest"; speedTestMethod = "networkquality"; commandPath = "" },
                [pscustomobject]@{ enabled = $true; service = "bt"; endpointName = "bt"; type = "speedtest"; speedTestMethod = "burst" }
            )
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues | Should -Contain "yt-dlp target 'yt/yt' requires videoUrl or url."
        $issues | Should -Contain "networkquality target 'nq/nq' requires downloadUrl/url for burst fallback or an explicit commandPath."
        $issues | Should -Contain "Burst target 'bt/bt' requires downloadUrl or url."
    }

    It "validates upload measurement methods" {
        $global:uploadUrlMeasurementMockResult = $false

        $config = [pscustomobject]@{
            probe = [pscustomobject]@{ probeId = "test" }
            influx = [pscustomobject]@{ baseUrl = "test"; bucket = "test"; tokenEnvVar = "test" }
            targets = @(
                [pscustomobject]@{ enabled = $true; service = "uu"; endpointName = "uu"; type = "speedtest"; speedTestMethod = "fast-cli"; uploadMethodMock = "upload-url" },
                [pscustomobject]@{ enabled = $true; service = "un"; endpointName = "un"; type = "speedtest"; speedTestMethod = "fast-cli"; uploadMethodMock = "unsupported-upload" }
            )
            probeRun = [pscustomobject]@{ defaultUploadMeasurementMethod = "none" }
        }
        $issues = Get-RequiredConfigIssues -Config $config
        $issues | Should -Contain "Target 'uu/uu' requires uploadUrl when uploadMeasurementMethod is 'upload-url'."
        $issues | Should -Contain "Target 'un/un' uses unsupported uploadMeasurementMethod 'unsupported-upload'."
    }
}
