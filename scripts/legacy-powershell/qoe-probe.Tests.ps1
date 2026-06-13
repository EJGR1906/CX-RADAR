BeforeAll {
    $scriptPath = Join-Path $PSScriptRoot "qoe-probe.ps1"
    $scriptContent = Get-Content $scriptPath -Raw

    $ast = [System.Management.Automation.Language.Parser]::ParseInput($scriptContent, [ref]$null, [ref]$null)
    $functionAst = $ast.Find({$args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $args[0].Name -eq 'ConvertTo-EscapedFieldString'}, $true)

    if ($null -ne $functionAst) {
        Invoke-Expression $functionAst.Extent.Text
    } else {
        throw "Function ConvertTo-EscapedFieldString not found."
    }
}

Describe "ConvertTo-EscapedFieldString" {
    It "returns empty string for null" {
        $result = ConvertTo-EscapedFieldString -Value $null
        $result | Should -Be ""
    }

    It "returns string representation for simple values" {
        $result = ConvertTo-EscapedFieldString -Value 123
        $result | Should -Be "123"

        $result2 = ConvertTo-EscapedFieldString -Value "test"
        $result2 | Should -Be "test"
    }

    It "escapes backslashes" {
        $result = ConvertTo-EscapedFieldString -Value "C:\Windows\System32"
        $result | Should -Be "C:\\Windows\\System32"
    }

    It "escapes double quotes" {
        $result = ConvertTo-EscapedFieldString -Value 'He said "Hello"'
        $result | Should -Be 'He said \"Hello\"'
    }

    It "handles both backslashes and double quotes" {
        $result = ConvertTo-EscapedFieldString -Value 'Path: "C:\test"'
        $result | Should -Be 'Path: \"C:\\test\"'
    }
}
