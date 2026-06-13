BeforeAll {
    # Extract functions from qoe-probe.ps1 without executing the script
    $ScriptPath = Join-Path $PSScriptRoot "..\qoe-probe.ps1"

    # Fallback for actual repo structure
    if (-not (Test-Path -Path $ScriptPath)) {
        $ScriptPath = Join-Path $PSScriptRoot "..\legacy-powershell\qoe-probe.ps1"
    }

    if (-not (Test-Path -Path $ScriptPath)) {
        Write-Error "Could not find qoe-probe.ps1 at $ScriptPath"
    }

    $ScriptContent = Get-Content -Path $ScriptPath -Raw
    $Ast = [System.Management.Automation.Language.Parser]::ParseInput($ScriptContent, [ref]$null, [ref]$null)

    # Recreate the function dynamically by explicitly dot-sourcing the Invoke-Expression string block
    # to register it in the caller scope (which inside BeforeAll maps to the test scope).
    $Ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true) |
        Where-Object { $_.Name -eq "ConvertTo-EscapedTagValue" } |
        ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }
}

Describe "ConvertTo-EscapedTagValue" {
    It "Returns empty string for null input" {
        $result = ConvertTo-EscapedTagValue -Value $null
        $result | Should -Be ''
    }

    It "Returns the same string for input without special characters" {
        $result = ConvertTo-EscapedTagValue -Value "NormalString123"
        $result | Should -Be "NormalString123"
    }

    It "Escapes spaces" {
        $result = ConvertTo-EscapedTagValue -Value "String with spaces"
        $result | Should -Be "String\ with\ spaces"
    }

    It "Escapes commas" {
        $result = ConvertTo-EscapedTagValue -Value "Value,1,2"
        $result | Should -Be "Value\,1\,2"
    }

    It "Escapes equal signs" {
        $result = ConvertTo-EscapedTagValue -Value "Key=Value"
        $result | Should -Be "Key\=Value"
    }

    It "Escapes backslashes" {
        $result = ConvertTo-EscapedTagValue -Value "C:\Path\To\File"
        $result | Should -Be "C:\\Path\\To\\File"
    }

    It "Escapes combinations of special characters" {
        $result = ConvertTo-EscapedTagValue -Value "Key, Name = Value\1"
        $result | Should -Be "Key\,\ Name\ \=\ Value\\1"
    }

    It "Handles boolean values by converting to string first" {
        $result = ConvertTo-EscapedTagValue -Value $true
        $result | Should -Be "True"
    }

    It "Handles integer values by converting to string first" {
        $result = ConvertTo-EscapedTagValue -Value 42
        $result | Should -Be "42"
    }
}
