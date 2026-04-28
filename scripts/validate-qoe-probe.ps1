[CmdletBinding()]
param(
    [Parameter()]
    [string]$ProbeScriptPath = '',

    [Parameter()]
    [string]$ConfigPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ScriptBasePath {
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        return $PSScriptRoot
    }

    if (-not [string]::IsNullOrWhiteSpace($PSCommandPath)) {
        return (Split-Path -Path $PSCommandPath -Parent)
    }

    if ($MyInvocation.MyCommand.Path) {
        return (Split-Path -Path $MyInvocation.MyCommand.Path -Parent)
    }

    return (Get-Location).Path
}

function Get-FullPathFromBase {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BasePath,

        [Parameter(Mandatory = $true)]
        [string]$ChildPath
    )

    $expandedChildPath = [Environment]::ExpandEnvironmentVariables($ChildPath)

    if ([System.IO.Path]::IsPathRooted($expandedChildPath)) {
        return [System.IO.Path]::GetFullPath($expandedChildPath)
    }

    return [System.IO.Path]::GetFullPath((Join-Path -Path $BasePath -ChildPath $expandedChildPath))
}

function Test-PowerShellSyntax {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors) | Out-Null

    if ($errors.Count -gt 0) {
        $messages = $errors | ForEach-Object {
            "{0} (Line {1}, Column {2})" -f $_.Message, $_.Extent.StartLineNumber, $_.Extent.StartColumnNumber
        }
        throw ($messages -join [Environment]::NewLine)
    }
}

function Get-RequiredConfigIssues {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config
    )

    $issues = New-Object System.Collections.Generic.List[string]

    if ([string]::IsNullOrWhiteSpace([string]$Config.probe.probeId)) {
        $issues.Add('probe.probeId is required.')
    }
    if ([string]::IsNullOrWhiteSpace([string]$Config.influx.baseUrl)) {
        $issues.Add('influx.baseUrl is required.')
    }
    if ([string]::IsNullOrWhiteSpace([string]$Config.influx.bucket)) {
        $issues.Add('influx.bucket is required.')
    }
    if ([string]::IsNullOrWhiteSpace([string]$Config.influx.tokenEnvVar)) {
        $issues.Add('influx.tokenEnvVar is required.')
    }
    if ($null -eq $Config.targets -or @($Config.targets).Count -eq 0) {
        $issues.Add('At least one enabled target is required.')
    }

    foreach ($target in $Config.targets) {
        if ($target.enabled -and [string]::IsNullOrWhiteSpace([string]$target.url)) {
            $issues.Add("Target '$($target.service)/$($target.endpointName)' is enabled but has no URL.")
        }
    }

    return $issues.ToArray()
}

function Get-InfluxTokenFromProtectedFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProtectedTokenFilePath
    )

    if (-not (Test-Path -Path $ProtectedTokenFilePath -PathType Leaf)) {
        return ''
    }

    $importedSecret = Import-Clixml -Path $ProtectedTokenFilePath
    if ($importedSecret -is [System.Management.Automation.PSCredential]) {
        return $importedSecret.GetNetworkCredential().Password
    }

    if ($importedSecret -is [securestring]) {
        $credential = New-Object System.Management.Automation.PSCredential('token', $importedSecret)
        return $credential.GetNetworkCredential().Password
    }

    throw "Protected token file '$ProtectedTokenFilePath' does not contain a PSCredential or SecureString object."
}

function Get-InfluxTokenStatus {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$InfluxConfig,

        [Parameter(Mandatory = $true)]
        [string]$ConfigDirectory
    )

    $protectedTokenFilePath = ''
    $protectedTokenFileExists = $false

    if ($InfluxConfig.PSObject.Properties.Name -contains 'credentialFilePath' -and -not [string]::IsNullOrWhiteSpace([string]$InfluxConfig.credentialFilePath)) {
        $protectedTokenFilePath = Get-FullPathFromBase -BasePath $ConfigDirectory -ChildPath ([string]$InfluxConfig.credentialFilePath)
        $protectedTokenFileExists = Test-Path -Path $protectedTokenFilePath -PathType Leaf
        if ($protectedTokenFileExists) {
            $credentialToken = Get-InfluxTokenFromProtectedFile -ProtectedTokenFilePath $protectedTokenFilePath
            if (-not [string]::IsNullOrWhiteSpace($credentialToken)) {
                return [pscustomobject]@{
                    Available = $true
                    Source = 'CredentialFile'
                    CredentialFilePath = $protectedTokenFilePath
                    CredentialFileExists = $protectedTokenFileExists
                }
            }
        }
    }

    $tokenName = [string]$InfluxConfig.tokenEnvVar
    $tokenValue = [Environment]::GetEnvironmentVariable($tokenName, 'Process')
    if ([string]::IsNullOrWhiteSpace($tokenValue)) {
        $tokenValue = [Environment]::GetEnvironmentVariable($tokenName, 'User')
    }

    return [pscustomobject]@{
        Available = -not [string]::IsNullOrWhiteSpace($tokenValue)
        Source = if (-not [string]::IsNullOrWhiteSpace($tokenValue)) { 'EnvironmentVariable' } else { 'None' }
        CredentialFilePath = $protectedTokenFilePath
        CredentialFileExists = $protectedTokenFileExists
    }
}

$scriptBasePath = Get-ScriptBasePath
if ([string]::IsNullOrWhiteSpace($ProbeScriptPath)) {
    $ProbeScriptPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath 'qoe-probe.ps1'
}

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\config\probe-catalog.json'
}

$resolvedProbeScriptPath = [System.IO.Path]::GetFullPath((Resolve-Path -Path $ProbeScriptPath).Path)
$resolvedConfigPath = [System.IO.Path]::GetFullPath((Resolve-Path -Path $ConfigPath).Path)

Test-PowerShellSyntax -Path $resolvedProbeScriptPath

$config = Get-Content -Path $resolvedConfigPath -Raw | ConvertFrom-Json
$configDirectory = Split-Path -Path $resolvedConfigPath -Parent
$issues = @(Get-RequiredConfigIssues -Config $config)
if ($issues.Count -gt 0) {
    throw ($issues -join [Environment]::NewLine)
}

$tokenStatus = Get-InfluxTokenStatus -InfluxConfig $config.influx -ConfigDirectory $configDirectory

$results = [ordered]@{
    ProbeScriptSyntax = 'OK'
    ConfigFile = 'OK'
    CurlAvailable = [bool](Get-Command -Name 'curl.exe' -ErrorAction SilentlyContinue)
    InfluxTokenAvailable = [bool]$tokenStatus.Available
    InfluxTokenSource = [string]$tokenStatus.Source
    InfluxCredentialFilePath = [string]$tokenStatus.CredentialFilePath
    InfluxCredentialFileExists = [bool]$tokenStatus.CredentialFileExists
    EnabledTargets = [int](@($config.targets | Where-Object { $_.enabled }).Count)
}

[pscustomobject]$results