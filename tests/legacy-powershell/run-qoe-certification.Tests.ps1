BeforeAll {
    $scriptContent = Get-Content -Path "$PSScriptRoot/../../scripts/legacy-powershell/run-qoe-certification.ps1" -Raw
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($scriptContent, [ref]$null, [ref]$null)
    $functionAst = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $args[0].Name -eq 'Test-LogCoverage' }, $true)
    Invoke-Expression $functionAst[0].Extent.Text
}

Describe "Test-LogCoverage Edge Cases" {
    It "Returns false when summary is null" {
        $log = [pscustomobject]@{
            summary = $null
            target_results = @(1, 2)
            line_count = 5
        }
        Test-LogCoverage -ParsedLog $log -ExpectedTargetCount 2 | Should -Be $false
    }

    It "Returns true when target count matches and line count is exactly ExpectedTargetCount + 3 (boundary)" {
        $log = [pscustomobject]@{
            summary = [pscustomobject]@{ success_count = 2 }
            target_results = @(1, 2)
            line_count = 5
        }
        Test-LogCoverage -ParsedLog $log -ExpectedTargetCount 2 | Should -Be $true
    }

    It "Returns true when line count is greater than ExpectedTargetCount + 3" {
        $log = [pscustomobject]@{
            summary = [pscustomobject]@{ success_count = 2 }
            target_results = @(1, 2)
            line_count = 6
        }
        Test-LogCoverage -ParsedLog $log -ExpectedTargetCount 2 | Should -Be $true
    }

    It "Returns false when line count is ExpectedTargetCount + 2 (edge case missing one line)" {
        $log = [pscustomobject]@{
            summary = [pscustomobject]@{ success_count = 2 }
            target_results = @(1, 2)
            line_count = 4
        }
        Test-LogCoverage -ParsedLog $log -ExpectedTargetCount 2 | Should -Be $false
    }

    It "Returns false when target results count is less than ExpectedTargetCount" {
        $log = [pscustomobject]@{
            summary = [pscustomobject]@{ success_count = 1 }
            target_results = @(1)
            line_count = 5
        }
        Test-LogCoverage -ParsedLog $log -ExpectedTargetCount 2 | Should -Be $false
    }

    It "Returns false when target results count is greater than ExpectedTargetCount" {
        $log = [pscustomobject]@{
            summary = [pscustomobject]@{ success_count = 3 }
            target_results = @(1, 2, 3)
            line_count = 6
        }
        Test-LogCoverage -ParsedLog $log -ExpectedTargetCount 2 | Should -Be $false
    }
}
