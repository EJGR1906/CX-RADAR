Describe "Get-TargetType" {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot "..\validate-qoe-probe.ps1"
        $scriptContent = Get-Content $scriptPath -Raw

        # Exclude top-level execution logic by only loading the function definitions
        # In validate-qoe-probe.ps1, execution logic begins at '$scriptBasePath = Get-ScriptBasePath'
        $functionDefinitions = $scriptContent.Substring(0, $scriptContent.IndexOf("`$scriptBasePath = Get-ScriptBasePath"))

        # Load functions into memory
        Invoke-Expression $functionDefinitions
    }

    It "should return the type property value in lowercase" {
        $mockTarget = [PSCustomObject]@{
            type = "HTTP"
        }

        Mock Get-OptionalStringValue {
            param($Source, $PropertyName, $DefaultValue)
            return "HTTP"
        }

        $result = Get-TargetType -Target $mockTarget

        $result | Should -Be "http"
        Assert-MockCalled Get-OptionalStringValue -Times 1 -Exactly -ParameterFilter {
            $Source.type -eq 'HTTP' -and $PropertyName -eq 'type' -and $DefaultValue -eq 'http'
        }
    }

    It "should use the default value when type is not provided" {
        $mockTarget = [PSCustomObject]@{
            other = "value"
        }

        Mock Get-OptionalStringValue {
            param($Source, $PropertyName, $DefaultValue)
            return "http"
        }

        $result = Get-TargetType -Target $mockTarget

        $result | Should -Be "http"
        Assert-MockCalled Get-OptionalStringValue -Times 1 -Exactly -ParameterFilter {
            $Source.other -eq 'value' -and $PropertyName -eq 'type' -and $DefaultValue -eq 'http'
        }
    }

    It "should handle unexpected uppercase values" {
        $mockTarget = [PSCustomObject]@{
            type = "SPEEDTEST"
        }

        Mock Get-OptionalStringValue {
            param($Source, $PropertyName, $DefaultValue)
            return "SPEEDTEST"
        }

        $result = Get-TargetType -Target $mockTarget

        $result | Should -Be "speedtest"
        Assert-MockCalled Get-OptionalStringValue -Times 1 -Exactly -ParameterFilter {
            $Source.type -eq 'SPEEDTEST' -and $PropertyName -eq 'type' -and $DefaultValue -eq 'http'
        }
    }
}
