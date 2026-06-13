$ErrorActionPreference = 'Stop'

Describe "Get-ExpectedHttpCodeMatch" {
    BeforeAll {
        # Load the target function from the main script using AST to avoid executing the script
        $scriptPath = Join-Path -Path $PSScriptRoot -ChildPath 'qoe-probe.ps1'
        $scriptContent = Get-Content -Path $scriptPath -Raw

        $ast = [System.Management.Automation.Language.Parser]::ParseInput($scriptContent, [ref]$null, [ref]$null)
        $functionAst = $ast.Find({
            param($astNode)
            $astNode -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $astNode.Name -eq 'Get-ExpectedHttpCodeMatch'
        }, $true)

        if (-not $functionAst) {
            throw "Could not find function 'Get-ExpectedHttpCodeMatch' in $scriptPath"
        }

        # Need to invoke expression to define function.
        # Using module makes it cleaner.
        $moduleText = "function Get-ExpectedHttpCodeMatch $($functionAst.Body.Extent.Text)"
        New-Module -ScriptBlock ([ScriptBlock]::Create($moduleText)) | Out-Null
    }

    It "Returns true when the HTTP code is exactly in the expected array" {
        $expectedCodes = @(200, 201, 202)
        $result = Get-ExpectedHttpCodeMatch -HttpCode 200 -ExpectedHttpCodes $expectedCodes
        $result | Should -Be $true
    }

    It "Returns true when the HTTP code matches another element in the array" {
        $expectedCodes = @(200, 201, 202)
        $result = Get-ExpectedHttpCodeMatch -HttpCode 202 -ExpectedHttpCodes $expectedCodes
        $result | Should -Be $true
    }

    It "Returns false when the HTTP code is not in the expected array" {
        $expectedCodes = @(200, 201, 202)
        $result = Get-ExpectedHttpCodeMatch -HttpCode 404 -ExpectedHttpCodes $expectedCodes
        $result | Should -Be $false
    }

    It "Returns false when the expected array is empty" {
        $expectedCodes = @()
        $result = Get-ExpectedHttpCodeMatch -HttpCode 200 -ExpectedHttpCodes $expectedCodes
        $result | Should -Be $false
    }

    It "Returns true when the expected array has only the matching code" {
        $expectedCodes = @(403)
        $result = Get-ExpectedHttpCodeMatch -HttpCode 403 -ExpectedHttpCodes $expectedCodes
        $result | Should -Be $true
    }

    It "Returns false when the expected array has only one element and it does not match" {
        $expectedCodes = @(200)
        $result = Get-ExpectedHttpCodeMatch -HttpCode 500 -ExpectedHttpCodes $expectedCodes
        $result | Should -Be $false
    }

    It "Handles negative codes properly" {
        $expectedCodes = @(200, -1)
        $result = Get-ExpectedHttpCodeMatch -HttpCode -1 -ExpectedHttpCodes $expectedCodes
        $result | Should -Be $true
    }

    It "Handles null or uninitialized ExpectedHttpCodes gracefully" {
        $result = Get-ExpectedHttpCodeMatch -HttpCode 200
        $result | Should -Be $false
    }
}
