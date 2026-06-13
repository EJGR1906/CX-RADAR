$ErrorActionPreference = 'Stop'

BeforeAll {
    $scriptPath = Resolve-Path "$PSScriptRoot/../legacy-powershell/qoe-probe.ps1"
    $scriptContent = Get-Content -Path $scriptPath -Raw
    $errors = $null
    $tokens = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($scriptContent, [ref]$tokens, [ref]$errors)

    $functionAst = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-MbpsFromBytesAndDuration'
    }, $true)[0]

    if ($null -eq $functionAst) {
        throw "Function Get-MbpsFromBytesAndDuration not found in $scriptPath"
    }

    # Execute the function definition to make it available in BeforeAll
    Invoke-Expression $functionAst.Extent.Text

    # Export it to global scope so It blocks can see it
    $funcDef = Get-Command Get-MbpsFromBytesAndDuration
    Set-Item -Path "Function:global:Get-MbpsFromBytesAndDuration" -Value $funcDef.ScriptBlock
}

Describe "Get-MbpsFromBytesAndDuration" {
    It "Calculates normal throughput correctly (10MB in 1 sec = 80 Mbps)" {
        $bytes = 10000000 # 10 MB
        $durationMs = 1000 # 1 second
        $result = Get-MbpsFromBytesAndDuration -Bytes $bytes -DurationMs $durationMs
        $result | Should -Be 80.0
    }

    It "Calculates standard values with rounding (1MB in 1.5 sec)" {
        $bytes = 1000000 # 1 MB
        $durationMs = 1500 # 1.5 seconds
        # 1MB * 8 = 8 Mb. 8 Mb / 1.5s = 5.333... Mbps. Round to 2 is 5.33
        $result = Get-MbpsFromBytesAndDuration -Bytes $bytes -DurationMs $durationMs
        $result | Should -Be 5.33
    }

    It "Returns 0.0 when Bytes is 0" {
        $result = Get-MbpsFromBytesAndDuration -Bytes 0 -DurationMs 1000
        $result | Should -Be 0.0
    }

    It "Returns 0.0 when Bytes is negative" {
        $result = Get-MbpsFromBytesAndDuration -Bytes -100 -DurationMs 1000
        $result | Should -Be 0.0
    }

    It "Returns 0.0 when DurationMs is 0" {
        $result = Get-MbpsFromBytesAndDuration -Bytes 1000000 -DurationMs 0
        $result | Should -Be 0.0
    }

    It "Returns 0.0 when DurationMs is negative" {
        $result = Get-MbpsFromBytesAndDuration -Bytes 1000000 -DurationMs -500
        $result | Should -Be 0.0
    }

    It "Returns 0.0 when both Bytes and DurationMs are 0" {
        $result = Get-MbpsFromBytesAndDuration -Bytes 0 -DurationMs 0
        $result | Should -Be 0.0
    }
}
