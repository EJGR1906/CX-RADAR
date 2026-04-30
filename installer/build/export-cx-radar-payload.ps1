[CmdletBinding()]
param(
    [Parameter()]
    [string]$OutputDirectory = '',

    [Parameter()]
    [string]$Version = '',

    [Parameter()]
    [string]$Channel = 'stable',

    [Parameter()]
    [string]$ManifestBaseUrl = ''
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

function Ensure-Directory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -Path $Path -PathType Container)) {
        New-Item -Path $Path -ItemType Directory -Force | Out-Null
    }
}

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $directory = Split-Path -Path $Path -Parent
    if (-not [string]::IsNullOrWhiteSpace($directory)) {
        Ensure-Directory -Path $directory
    }

    $utf8Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8Encoding)
}

$scriptBasePath = Get-ScriptBasePath
$installerRoot = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..'
$repoRoot = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\..'

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Get-FullPathFromBase -BasePath $repoRoot -ChildPath 'dist\installer'
}
else {
    $OutputDirectory = Get-FullPathFromBase -BasePath $repoRoot -ChildPath $OutputDirectory
}

Ensure-Directory -Path $OutputDirectory

$probeConfig = Get-Content -Path (Get-FullPathFromBase -BasePath $repoRoot -ChildPath 'config\probe-catalog.json') -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = [string]$probeConfig.probe.probeVersion
}

$layout = Get-Content -Path (Get-FullPathFromBase -BasePath $installerRoot -ChildPath 'payload-layout.json') -Raw | ConvertFrom-Json
$stagingRoot = Join-Path -Path $OutputDirectory -ChildPath ('payload-{0}' -f $Version)
if (Test-Path -Path $stagingRoot) {
    Remove-Item -Path $stagingRoot -Recurse -Force
}

Ensure-Directory -Path $stagingRoot

foreach ($mapping in @($layout.payloadFiles)) {
    $sourcePath = Get-FullPathFromBase -BasePath $repoRoot -ChildPath ([string]$mapping.source)
    if (-not (Test-Path -Path $sourcePath -PathType Leaf)) {
        throw "Payload source file '$sourcePath' does not exist."
    }

    $targetPath = Get-FullPathFromBase -BasePath $stagingRoot -ChildPath ([string]$mapping.target)
    $targetDirectory = Split-Path -Path $targetPath -Parent
    Ensure-Directory -Path $targetDirectory
    Copy-Item -Path $sourcePath -Destination $targetPath -Force
}

$templateTargets = @(
    'templates\probe-catalog.template.json',
    'templates\speed-test-catalog.template.json',
    'schema\state.schema.json'
)

foreach ($relativePath in $templateTargets) {
    $sourcePath = Get-FullPathFromBase -BasePath $installerRoot -ChildPath $relativePath
    $targetPath = Get-FullPathFromBase -BasePath $stagingRoot -ChildPath ('installer\{0}' -f $relativePath)
    $targetDirectory = Split-Path -Path $targetPath -Parent
    Ensure-Directory -Path $targetDirectory
    Copy-Item -Path $sourcePath -Destination $targetPath -Force
}

$zipPath = Join-Path -Path $OutputDirectory -ChildPath ('cx-radar-payload-{0}.zip' -f $Version)
if (Test-Path -Path $zipPath -PathType Leaf) {
    Remove-Item -Path $zipPath -Force
}

Compress-Archive -Path (Join-Path -Path $stagingRoot -ChildPath '*') -DestinationPath $zipPath -CompressionLevel Optimal
$hash = Get-FileHash -Path $zipPath -Algorithm SHA256
$manifest = [ordered]@{
    channel = $Channel
    version = $Version
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    bootstrapMode = 'payload-archive'
    payload = [ordered]@{
        fileName = [System.IO.Path]::GetFileName($zipPath)
        sha256 = $hash.Hash.ToLowerInvariant()
        sizeBytes = [int64](Get-Item -Path $zipPath).Length
    }
}

if (-not [string]::IsNullOrWhiteSpace($ManifestBaseUrl)) {
    $trimmedBaseUrl = $ManifestBaseUrl.TrimEnd('/')
    $manifest.payload.url = '{0}/{1}' -f $trimmedBaseUrl, [System.IO.Path]::GetFileName($zipPath)
}

$manifestPath = Join-Path -Path $OutputDirectory -ChildPath 'manifest.json'
Write-Utf8File -Path $manifestPath -Content (($manifest | ConvertTo-Json -Depth 6) + [Environment]::NewLine)

[pscustomobject]@{
    Version = $Version
    Channel = $Channel
    PayloadZipPath = $zipPath
    PayloadSha256 = $hash.Hash.ToLowerInvariant()
    ManifestPath = $manifestPath
    StagingPath = $stagingRoot
}