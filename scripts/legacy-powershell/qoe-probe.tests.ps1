Describe "Get-OptionalIntValue" {
    BeforeAll {
        $scriptContent = Get-Content -Path $PSScriptRoot/qoe-probe.ps1 -Raw
        $functionDefinition = $scriptContent -match '(?ms)function Get-OptionalIntValue \{.*?\n\}'
        if ($matches) {
            Invoke-Expression $matches[0]
        } else {
            throw "Could not find function Get-OptionalIntValue"
        }
    }

    It "should extract existing integer values" {
        $testObj = [pscustomobject]@{ MyInt = 42 }
        $result = Get-OptionalIntValue -Source $testObj -PropertyName 'MyInt' -DefaultValue 10
        $result | Should -Be 42
    }

    It "should extract negative integer values" {
        $testObj = [pscustomobject]@{ MyInt = -50 }
        $result = Get-OptionalIntValue -Source $testObj -PropertyName 'MyInt' -DefaultValue 10
        $result | Should -Be -50
    }

    It "should use the default value when the key is missing" {
        $testObj = [pscustomobject]@{ OtherKey = 42 }
        $result = Get-OptionalIntValue -Source $testObj -PropertyName 'MyInt' -DefaultValue 10
        $result | Should -Be 10
    }

    It "should use the default value when the key exists but is null" {
        $testObj = [pscustomobject]@{ MyInt = $null }
        $result = Get-OptionalIntValue -Source $testObj -PropertyName 'MyInt' -DefaultValue 15
        $result | Should -Be 15
    }

    It "should handle string numbers if they can be cast to int" {
        $testObj = [pscustomobject]@{ MyInt = "123" }
        $result = Get-OptionalIntValue -Source $testObj -PropertyName 'MyInt' -DefaultValue 10
        $result | Should -Be 123
    }
}
