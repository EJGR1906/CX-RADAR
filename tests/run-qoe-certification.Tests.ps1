$scriptPath = "$PSScriptRoot/../scripts/legacy-powershell/run-qoe-certification.ps1"
if (-not (Test-Path $scriptPath)) {
    $scriptPath = "$PSScriptRoot/../scripts/run-qoe-certification.ps1"
}

$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$null, [ref]$null)

$functionAst = $ast.Find({
    param($astNode)
    $astNode -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $astNode.Name -eq 'ConvertTo-InvariantDouble'
}, $true)

if ($functionAst) {
    Invoke-Expression "function global:ConvertTo-InvariantDouble $($functionAst.Body.Extent.Text)"
}

Describe "ConvertTo-InvariantDouble" {
    It "converts a simple double string with period" {
        $result = ConvertTo-InvariantDouble -Value "123.45"
        $result | Should -Be 123.45
    }

    It "converts a double string with comma" {
        $result = ConvertTo-InvariantDouble -Value "123,45"
        $result | Should -Be 123.45
    }

    It "handles whole numbers" {
        $result = ConvertTo-InvariantDouble -Value "100"
        $result | Should -Be 100.0
    }

    It "throws an error for non-numeric strings" {
        { ConvertTo-InvariantDouble -Value "abc" } | Should -Throw
    }

    It "throws an error for empty strings" {
        { ConvertTo-InvariantDouble -Value "" } | Should -Throw
    }
}
