Describe "validate-qoe-probe.ps1" {
    BeforeAll {
        $script:sutPath = Join-Path $PSScriptRoot "validate-qoe-probe.ps1"
    }

    Context "File existence" {
        It "Should exist" {
            (Test-Path $script:sutPath) | Should -Be $true
        }
    }

    Context "Execution" {
        It "Should execute without errors" {
            $result = & $script:sutPath
            $result | Should -BeNullOrEmpty
        }
    }
}
