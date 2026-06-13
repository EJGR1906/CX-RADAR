BeforeAll {
    # Extract function safely using AST to avoid running the script
    $scriptPath = "$PSScriptRoot/../legacy-powershell/qoe-probe.ps1"

    # Check if the file exists at the legacy-powershell path (where we found it), else check standard path
    if (-not (Test-Path $scriptPath)) {
        $scriptPath = "$PSScriptRoot/../qoe-probe.ps1"
    }

    $scriptContent = Get-Content -Path $scriptPath -Raw
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($scriptContent, [ref]$null, [ref]$null)
    $functionAst = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $args[0].Name -eq "Get-ApproximateRpmFromLatency" }, $true)

    if ($functionAst) {
        $functionDefinition = $functionAst[0].Extent.Text
        Invoke-Expression $functionDefinition
    } else {
        throw "Could not find Get-ApproximateRpmFromLatency in qoe-probe.ps1"
    }
}

Describe "Get-ApproximateRpmFromLatency" {
    Context "When LatencyMs is valid" {
        It "Returns expected RPM for a typical latency" {
            $result = Get-ApproximateRpmFromLatency -LatencyMs 50
            $result | Should -Be 1200
        }

        It "Returns expected RPM for a high latency" {
            $result = Get-ApproximateRpmFromLatency -LatencyMs 1000
            $result | Should -Be 60
        }
    }

    Context "When LatencyMs is invalid or edge case" {
        It "Returns 0.0 for LatencyMs of 0" {
            $result = Get-ApproximateRpmFromLatency -LatencyMs 0
            $result | Should -Be 0.0
        }

        It "Returns 0.0 for negative LatencyMs" {
            $result = Get-ApproximateRpmFromLatency -LatencyMs -1
            $result | Should -Be 0.0
        }
    }
}
