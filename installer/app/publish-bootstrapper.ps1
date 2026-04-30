[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',

    [Parameter()]
    [string]$RuntimeIdentifier = 'win-x64',

    [Parameter()]
    [string]$OutputDirectory = '',

    [Parameter()]
    [switch]$SelfContained,

    [Parameter()]
    [switch]$ZipOutput
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

function New-DirectoryIfMissing {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -Path $Path -PathType Container)) {
        New-Item -Path $Path -ItemType Directory -Force | Out-Null
    }
}

$scriptBasePath = Get-ScriptBasePath
$projectPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath 'CXRadar.Bootstrapper\CXRadar.Bootstrapper.csproj'

if (-not (Get-Command -Name 'dotnet' -ErrorAction SilentlyContinue)) {
    throw 'The .NET SDK was not found. Install the SDK and rerun publish-bootstrapper.ps1.'
}

$sdkListOutput = @(& dotnet --list-sdks 2>&1)
if ($LASTEXITCODE -ne 0 -or $sdkListOutput.Count -eq 0) {
    throw 'The dotnet host is present, but no .NET SDK is installed. Install the SDK and rerun publish-bootstrapper.ps1.'
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\..\dist\operator-bundle\bootstrapper'
}
else {
    $OutputDirectory = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath $OutputDirectory
}

New-DirectoryIfMissing -Path $OutputDirectory

$publishPath = Join-Path -Path $OutputDirectory -ChildPath $RuntimeIdentifier
if (Test-Path -Path $publishPath -PathType Container) {
    Remove-Item -Path $publishPath -Recurse -Force
}

$dotnetArguments = @(
    'publish', $projectPath,
    '-c', $Configuration,
    '-r', $RuntimeIdentifier,
    '--output', $publishPath,
    '/p:PublishSingleFile=true',
    '/p:IncludeNativeLibrariesForSelfExtract=true',
    '/p:EnableCompressionInSingleFile=true',
    '/p:DebugType=none'
)

if ($SelfContained) {
    $dotnetArguments += '--self-contained'
    $dotnetArguments += 'true'
}
else {
    $dotnetArguments += '--self-contained'
    $dotnetArguments += 'false'
}

& dotnet @dotnetArguments
if ($LASTEXITCODE -ne 0) {
    throw "dotnet publish failed with exit code $LASTEXITCODE."
}

$zipPath = ''
if ($ZipOutput) {
    $zipPath = Join-Path -Path $OutputDirectory -ChildPath ('CX-Radar-Bootstrapper-{0}.zip' -f $RuntimeIdentifier)
    if (Test-Path -Path $zipPath -PathType Leaf) {
        Remove-Item -Path $zipPath -Force
    }

    Compress-Archive -Path (Join-Path -Path $publishPath -ChildPath '*') -DestinationPath $zipPath -CompressionLevel Optimal
}

[pscustomobject]@{
    ProjectPath = $projectPath
    PublishPath = $publishPath
    ZipPath = $zipPath
    RuntimeIdentifier = $RuntimeIdentifier
    SelfContained = [bool]$SelfContained
}