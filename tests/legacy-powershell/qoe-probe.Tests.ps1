BeforeAll {
    $scriptContent = Get-Content -Path "$PSScriptRoot/../../scripts/legacy-powershell/qoe-probe.ps1" -Raw
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($scriptContent, [ref]$null, [ref]$null)
    $functionDefs = $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)

    $functionsOnly = ""
    foreach ($func in $functionDefs) {
        $functionsOnly += $func.Extent.Text + "`n`n"
    }

    Invoke-Expression $functionsOnly
}

Describe "Get-ParsedValue" {
    It "Returns default value when key is missing" {
        $map = @{
            "some_key" = "some_value"
        }
        $result = Get-ParsedValue -Map $map -Key "missing_key" -DefaultValue "default"
        $result | Should -Be "default"
    }

    It "Returns default value when value is null" {
        $map = @{
            "null_key" = $null
        }
        $result = Get-ParsedValue -Map $map -Key "null_key" -DefaultValue "default"
        $result | Should -Be "default"
    }

    It "Returns default value when value is empty string" {
        $map = @{
            "empty_key" = ""
        }
        $result = Get-ParsedValue -Map $map -Key "empty_key" -DefaultValue "default"
        $result | Should -Be "default"
    }

    It "Returns default value when value is whitespace string" {
        $map = @{
            "whitespace_key" = "   "
        }
        $result = Get-ParsedValue -Map $map -Key "whitespace_key" -DefaultValue "default"
        $result | Should -Be "default"
    }

    It "Returns the correct value when the key is present and not null/empty" {
        $map = @{
            "some_key" = "actual_value"
        }
        $result = Get-ParsedValue -Map $map -Key "some_key" -DefaultValue "default"
        $result | Should -Be "actual_value"
    }
}
