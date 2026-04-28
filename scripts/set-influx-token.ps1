[CmdletBinding()]
param(
    [Parameter()]
    [string]$ConfigPath = '',

    [Parameter()]
    [Alias('CredentialFilePath')]
    [string]$TokenStorePath = '',

    [Parameter()]
    [securestring]$Token,

    [Parameter()]
    [switch]$Force,

    [Parameter()]
    [switch]$ClearUserEnvironmentVariable
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

$scriptBasePath = Get-ScriptBasePath
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\config\probe-catalog.json'
}

$resolvedConfigPath = [System.IO.Path]::GetFullPath((Resolve-Path -Path $ConfigPath).Path)
$config = Get-Content -Path $resolvedConfigPath -Raw | ConvertFrom-Json
$configDirectory = Split-Path -Path $resolvedConfigPath -Parent

if ([string]::IsNullOrWhiteSpace($TokenStorePath)) {
    if ($config.influx.PSObject.Properties.Name -contains 'credentialFilePath' -and -not [string]::IsNullOrWhiteSpace([string]$config.influx.credentialFilePath)) {
        $TokenStorePath = [string]$config.influx.credentialFilePath
    }
    else {
        $TokenStorePath = '%LOCALAPPDATA%\CX-Radar\secrets\influxdb-token.credential.xml'
    }
}

$resolvedCredentialFilePath = Get-FullPathFromBase -BasePath $configDirectory -ChildPath $TokenStorePath
$secretDirectory = Split-Path -Path $resolvedCredentialFilePath -Parent
if (-not (Test-Path -Path $secretDirectory -PathType Container)) {
    New-Item -Path $secretDirectory -ItemType Directory -Force | Out-Null
}

if ((Test-Path -Path $resolvedCredentialFilePath -PathType Leaf) -and -not $Force) {
    throw "Protected token file '$resolvedCredentialFilePath' already exists. Use -Force to overwrite it."
}

if ($null -eq $Token) {
    $Token = Read-Host -Prompt 'Enter InfluxDB Cloud API token' -AsSecureString
}

$credential = New-Object System.Management.Automation.PSCredential('influxdb-token', $Token)
$credential | Export-Clixml -Path $resolvedCredentialFilePath -Force

$tokenEnvVarName = [string]$config.influx.tokenEnvVar
if ($ClearUserEnvironmentVariable -and -not [string]::IsNullOrWhiteSpace($tokenEnvVarName)) {
    [Environment]::SetEnvironmentVariable($tokenEnvVarName, $null, 'User')
}

[pscustomobject]@{
    CredentialFilePath = $resolvedCredentialFilePath
    TokenEnvironmentVariable = $tokenEnvVarName
    ClearedUserEnvironmentVariable = [bool]$ClearUserEnvironmentVariable
}