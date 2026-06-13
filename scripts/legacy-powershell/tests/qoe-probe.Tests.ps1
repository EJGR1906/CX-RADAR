$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptPath = Resolve-Path "$PSScriptRoot/../qoe-probe.ps1"
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$null, [ref]$null)

$functionAst = $ast.Find({
    param($astNode)
    $astNode -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $astNode.Name -eq 'ConvertTo-DoubleOrDefault'
}, $true)

if (-not $functionAst) {
    throw "Could not find function ConvertTo-DoubleOrDefault"
}

# Add global scope
$funcBody = $functionAst.Extent.Text -replace "function ConvertTo-DoubleOrDefault", "function global:ConvertTo-DoubleOrDefault"
Invoke-Expression $funcBody

Describe "ConvertTo-DoubleOrDefault" {
    It "Returns DefaultValue when Value is null" {
        $result = ConvertTo-DoubleOrDefault -Value $null -DefaultValue 42.0
        $result | Should -BeExactly 42.0
    }

    It "Returns DefaultValue when Value is empty string" {
        $result = ConvertTo-DoubleOrDefault -Value "" -DefaultValue 42.0
        $result | Should -BeExactly 42.0
    }

    It "Returns DefaultValue when Value is whitespace string" {
        $result = ConvertTo-DoubleOrDefault -Value "   " -DefaultValue 42.0
        $result | Should -BeExactly 42.0
    }

    It "Returns parsed double when Value is a valid double string" {
        $result = ConvertTo-DoubleOrDefault -Value "123.45" -DefaultValue 42.0
        $result | Should -BeExactly 123.45
    }

    It "Returns valid double when Value is already a double" {
        $result = ConvertTo-DoubleOrDefault -Value 123.45 -DefaultValue 42.0
        $result | Should -BeExactly 123.45
    }

    It "Returns DefaultValue when Value is an invalid double string (error path)" {
        $result = ConvertTo-DoubleOrDefault -Value "not a number" -DefaultValue 42.0
        $result | Should -BeExactly 42.0
    }
}
