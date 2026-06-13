$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $here "run-qoe-certification.ps1"

# Extract the Get-ParsedLogFailureCount function to avoid executing the rest of the script.
$scriptContent = Get-Content -Path $scriptPath -Raw
$ast = [System.Management.Automation.Language.Parser]::ParseInput($scriptContent, [ref]$null, [ref]$null)
$functionAst = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $args[0].Name -eq 'Get-ParsedLogFailureCount' }, $true)

if (-not $functionAst) {
    throw "Could not find function Get-ParsedLogFailureCount in $scriptPath"
}

Invoke-Expression "function global:Get-ParsedLogFailureCount $($functionAst.Body.Extent.Text)"

Describe "Get-ParsedLogFailureCount" {
    It "Returns -1 when ParsedLog.summary is null" {
        $parsedLog = [pscustomobject]@{
            summary = $null
        }

        $result = Get-ParsedLogFailureCount -ParsedLog $parsedLog

        $result | Should -Be -1
    }

    It "Returns the failure_count as an integer when summary is present" {
        $parsedLog = [pscustomobject]@{
            summary = [pscustomobject]@{
                failure_count = 5
            }
        }

        $result = Get-ParsedLogFailureCount -ParsedLog $parsedLog

        $result | Should -Be 5
    }
}
