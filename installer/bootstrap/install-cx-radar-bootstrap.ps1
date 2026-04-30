[CmdletBinding()]
param(
    [Parameter()]
    [string]$HubName = '',

    [Parameter()]
    [securestring]$InfluxToken,

    [Parameter()]
    [string]$InstallRoot = '%LOCALAPPDATA%\CX-Radar',

    [Parameter()]
    [string]$UpdateChannel = 'stable',

    [Parameter()]
    [string]$EnvironmentName = 'production',

    [Parameter()]
    [string]$ProbeType = 'windows-powershell',

    [Parameter()]
    [string]$SpeedTestCliSourcePath = '',

    [Parameter()]
    [switch]$NonInteractive,

    [Parameter()]
    [switch]$SkipValidation,

    [Parameter()]
    [switch]$SkipDryRun,

    [Parameter()]
    [switch]$SkipTaskRegistration,

    [Parameter()]
    [switch]$Force
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

function Write-Utf8JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $parent = Split-Path -Path $Path -Parent
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-DirectoryIfMissing -Path $parent
    }

    $utf8Encoding = New-Object System.Text.UTF8Encoding($false)
    $json = ($Value | ConvertTo-Json -Depth 10) + [Environment]::NewLine
    [System.IO.File]::WriteAllText($Path, $json, $utf8Encoding)
}

function Get-NormalizedSlug {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $normalized = $Value.Trim().ToLowerInvariant()
    $normalized = [System.Text.RegularExpressions.Regex]::Replace($normalized, '[^a-z0-9]+', '-')
    $normalized = [System.Text.RegularExpressions.Regex]::Replace($normalized, '-{2,}', '-')
    $normalized = $normalized.Trim('-')

    if ([string]::IsNullOrWhiteSpace($normalized)) {
        throw 'Hub name must contain at least one letter or digit after normalization.'
    }

    return $normalized
}

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return (Get-Content -Path $Path -Raw | ConvertFrom-Json)
}

function Get-ExistingState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StatePath
    )

    if (-not (Test-Path -Path $StatePath -PathType Leaf)) {
        return $null
    }

    return (Read-JsonFile -Path $StatePath)
}

function Get-InstallationState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$HubName,

        [Parameter(Mandatory = $true)]
        [string]$InstallRoot,

        [Parameter(Mandatory = $true)]
        [string]$CurrentRoot,

        [Parameter(Mandatory = $true)]
        [string]$StatePath,

        [Parameter(Mandatory = $true)]
        [string]$UpdateChannel,

        [Parameter(Mandatory = $true)]
        [string]$EnvironmentName,

        [Parameter(Mandatory = $true)]
        [string]$ProbeType,

        [Parameter(Mandatory = $true)]
        [string]$ProbeVersion,

        [Parameter()]
        [switch]$Force
    )

    $normalizedHub = Get-NormalizedSlug -Value $HubName
    $existingState = Get-ExistingState -StatePath $StatePath

    if ($null -ne $existingState) {
        if ($existingState.site -ne $normalizedHub -and -not $Force) {
            throw "Existing installation is bound to HUB '$($existingState.hubName)' and site '$($existingState.site)'. Use -Force to re-enroll explicitly."
        }

        $existingState.hubName = $HubName.Trim()
        $existingState.site = $normalizedHub
        $existingState.updateChannel = $UpdateChannel
        $existingState.environment = $EnvironmentName
        $existingState.probeType = $ProbeType
        $existingState.installedVersion = $ProbeVersion
        $existingState.lastUpdatedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
        $existingState.paths.installRoot = $InstallRoot
        $existingState.paths.currentRoot = $CurrentRoot
        $existingState.paths.statePath = $StatePath
        return $existingState
    }

    $installationId = [guid]::NewGuid().ToString('N')
    $probeSuffix = $installationId.Substring(0, 8)
    $nowUtc = (Get-Date).ToUniversalTime().ToString('o')

    return [pscustomobject]@{
        hubName = $HubName.Trim()
        site = $normalizedHub
        probeId = '{0}-{1}' -f $normalizedHub, $probeSuffix
        installationId = $installationId
        bootstrapMode = 'repo-bootstrap-script'
        installedVersion = $ProbeVersion
        updateChannel = $UpdateChannel
        environment = $EnvironmentName
        probeType = $ProbeType
        installedAtUtc = $nowUtc
        lastUpdatedAtUtc = $nowUtc
        paths = [pscustomobject]@{
            installRoot = $InstallRoot
            currentRoot = $CurrentRoot
            statePath = $StatePath
        }
    }
}

function Copy-PayloadFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$InstallerRoot,

        [Parameter(Mandatory = $true)]
        [string]$CurrentRoot
    )

    $layoutPath = Get-FullPathFromBase -BasePath $InstallerRoot -ChildPath 'payload-layout.json'
    $layout = Read-JsonFile -Path $layoutPath

    foreach ($mapping in @($layout.payloadFiles)) {
        $sourcePath = Get-FullPathFromBase -BasePath $RepoRoot -ChildPath ([string]$mapping.source)
        if (-not (Test-Path -Path $sourcePath -PathType Leaf)) {
            throw "Payload source file '$sourcePath' does not exist."
        }

        $targetPath = Get-FullPathFromBase -BasePath $CurrentRoot -ChildPath ([string]$mapping.target)
        $targetDirectory = Split-Path -Path $targetPath -Parent
        New-DirectoryIfMissing -Path $targetDirectory
        Copy-Item -Path $sourcePath -Destination $targetPath -Force
    }
}

function New-ConfigFromTemplate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TemplatePath,

        [Parameter(Mandatory = $true)]
        [string]$ProbeId,

        [Parameter(Mandatory = $true)]
        [string]$Site,

        [Parameter(Mandatory = $true)]
        [string]$EnvironmentName,

        [Parameter(Mandatory = $true)]
        [string]$ProbeType,

        [Parameter(Mandatory = $true)]
        [string]$ProbeVersion
    )

    $config = Read-JsonFile -Path $TemplatePath
    $config.probe.probeId = $ProbeId
    $config.probe.site = $Site
    $config.probe.environment = $EnvironmentName
    $config.probe.probeType = $ProbeType
    $config.probe.probeVersion = $ProbeVersion

    if ($config.PSObject.Properties.Name -contains 'probeRun') {
        $config.probeRun.userAgent = 'CX-Radar-QoE-Probe/{0}' -f $ProbeVersion
    }

    return $config
}

function Resolve-SpeedTestCliSeedPath {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$RequestedSourcePath,

        [Parameter(Mandatory = $true)]
        [string]$InstallRoot
    )

    $targetCliPath = Get-FullPathFromBase -BasePath $InstallRoot -ChildPath 'tools\ookla-speedtest\speedtest.exe'
    if (Test-Path -Path $targetCliPath -PathType Leaf) {
        return $targetCliPath
    }

    $defaultCliPath = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables('%LOCALAPPDATA%\CX-Radar\tools\ookla-speedtest\speedtest.exe'))
    if (Test-Path -Path $defaultCliPath -PathType Leaf) {
        return $defaultCliPath
    }

    if (-not [string]::IsNullOrWhiteSpace($RequestedSourcePath)) {
        $resolvedRequestedSourcePath = Get-FullPathFromBase -BasePath (Get-Location).Path -ChildPath $RequestedSourcePath
        if (-not (Test-Path -Path $resolvedRequestedSourcePath -PathType Leaf)) {
            throw "Speed-test CLI source '$resolvedRequestedSourcePath' does not exist."
        }

        return $resolvedRequestedSourcePath
    }

    $command = Get-Command -Name 'speedtest' -ErrorAction SilentlyContinue
    if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace([string]$command.Source)) {
        return [System.IO.Path]::GetFullPath([string]$command.Source)
    }

    $command = Get-Command -Name 'speedtest.exe' -ErrorAction SilentlyContinue
    if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace([string]$command.Source)) {
        return [System.IO.Path]::GetFullPath([string]$command.Source)
    }

    return ''
}

function Install-SpeedTestCli {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ResolvedSourcePath,

        [Parameter(Mandatory = $true)]
        [string]$InstallRoot
    )

    if ([string]::IsNullOrWhiteSpace($ResolvedSourcePath)) {
        return ''
    }

    $targetPath = Get-FullPathFromBase -BasePath $InstallRoot -ChildPath 'tools\ookla-speedtest\speedtest.exe'
    $targetDirectory = Split-Path -Path $targetPath -Parent
    New-DirectoryIfMissing -Path $targetDirectory

    if (([System.IO.Path]::GetFullPath($ResolvedSourcePath)) -ne ([System.IO.Path]::GetFullPath($targetPath))) {
        Copy-Item -Path $ResolvedSourcePath -Destination $targetPath -Force
    }

    return $targetPath
}

function Get-InfluxCredentialFilePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath
    )

    $config = Read-JsonFile -Path $ConfigPath
    $configDirectory = Split-Path -Path $ConfigPath -Parent
    return (Get-FullPathFromBase -BasePath $configDirectory -ChildPath ([string]$config.influx.credentialFilePath))
}

function Set-InfluxTokenIfNeeded {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SetTokenScriptPath,

        [Parameter(Mandatory = $true)]
        [string]$ConfigPath,

        [Parameter()]
        [securestring]$InfluxToken,

        [Parameter()]
        [switch]$NonInteractive,

        [Parameter()]
        [switch]$Force
    )

    $credentialFilePath = Get-InfluxCredentialFilePath -ConfigPath $ConfigPath
    if ($null -eq $InfluxToken -and (Test-Path -Path $credentialFilePath -PathType Leaf)) {
        return $credentialFilePath
    }

    if ($null -eq $InfluxToken -and $NonInteractive) {
        throw "Influx token is required for non-interactive bootstrap when the protected credential file does not already exist at '$credentialFilePath'."
    }

    $arguments = @(
        '-ConfigPath', $ConfigPath
    )

    if ($Force) {
        $arguments += '-Force'
    }

    if ($null -ne $InfluxToken) {
        & $SetTokenScriptPath @arguments -Token $InfluxToken | Out-Null
    }
    else {
        & $SetTokenScriptPath @arguments | Out-Null
    }

    return $credentialFilePath
}

function Invoke-ValidationScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,

        [Parameter(Mandatory = $true)]
        [string]$ProbeScriptPath,

        [Parameter(Mandatory = $true)]
        [string]$ConfigPath
    )

    return (& $ScriptPath -ProbeScriptPath $ProbeScriptPath -ConfigPath $ConfigPath)
}

function Assert-ValidationResult {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$ValidationResult,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    foreach ($property in $ValidationResult.PSObject.Properties) {
        if ($property.Name -like '*Available' -or $property.Name -like '*Exists') {
            if (-not [bool]$property.Value) {
                throw "$Label validation failed because '$($property.Name)' is false."
            }
        }
    }
}

function Invoke-DryRunScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,

        [Parameter(Mandatory = $true)]
        [string]$ConfigPath,

        [Parameter(Mandatory = $true)]
        [string]$ReportPath
    )

    return (& $ScriptPath -ConfigPath $ConfigPath -SkipInfluxWrite -RunReportPath $ReportPath)
}

$scriptBasePath = Get-ScriptBasePath
$installerRoot = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..'
$repoRoot = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\..'

if ([string]::IsNullOrWhiteSpace($HubName)) {
    if ($NonInteractive) {
        throw 'HubName is required in non-interactive mode.'
    }

    $HubName = Read-Host -Prompt 'Enter HUB name'
}

if ([string]::IsNullOrWhiteSpace($HubName)) {
    throw 'HubName is required.'
}

$InstallRoot = Get-FullPathFromBase -BasePath $repoRoot -ChildPath $InstallRoot
$currentRoot = Get-FullPathFromBase -BasePath $InstallRoot -ChildPath 'current'
$stateRoot = Get-FullPathFromBase -BasePath $InstallRoot -ChildPath 'state'
$packagesRoot = Get-FullPathFromBase -BasePath $InstallRoot -ChildPath 'packages'
$logsRoot = Get-FullPathFromBase -BasePath $InstallRoot -ChildPath 'logs'
$reportsRoot = Get-FullPathFromBase -BasePath $InstallRoot -ChildPath 'reports'
$statePath = Join-Path -Path $stateRoot -ChildPath 'state.json'

foreach ($directory in @($InstallRoot, $currentRoot, $stateRoot, $packagesRoot, $logsRoot, $reportsRoot)) {
    New-DirectoryIfMissing -Path $directory
}

$probeTemplatePath = Get-FullPathFromBase -BasePath $installerRoot -ChildPath 'templates\probe-catalog.template.json'
$speedTemplatePath = Get-FullPathFromBase -BasePath $installerRoot -ChildPath 'templates\speed-test-catalog.template.json'
$defaultProbeConfig = Read-JsonFile -Path (Get-FullPathFromBase -BasePath $repoRoot -ChildPath 'config\probe-catalog.json')
$probeVersion = [string]$defaultProbeConfig.probe.probeVersion

$state = Get-InstallationState -HubName $HubName -InstallRoot $InstallRoot -CurrentRoot $currentRoot -StatePath $statePath -UpdateChannel $UpdateChannel -EnvironmentName $EnvironmentName -ProbeType $ProbeType -ProbeVersion $probeVersion -Force:$Force
Copy-PayloadFiles -RepoRoot $repoRoot -InstallerRoot $installerRoot -CurrentRoot $currentRoot

$probeConfig = New-ConfigFromTemplate -TemplatePath $probeTemplatePath -ProbeId ([string]$state.probeId) -Site ([string]$state.site) -EnvironmentName $EnvironmentName -ProbeType $ProbeType -ProbeVersion $probeVersion
$speedConfig = New-ConfigFromTemplate -TemplatePath $speedTemplatePath -ProbeId ([string]$state.probeId) -Site ([string]$state.site) -EnvironmentName $EnvironmentName -ProbeType $ProbeType -ProbeVersion $probeVersion

$configRoot = Get-FullPathFromBase -BasePath $currentRoot -ChildPath 'config'
New-DirectoryIfMissing -Path $configRoot

$probeConfigPath = Join-Path -Path $configRoot -ChildPath 'probe-catalog.json'
$speedConfigPath = Join-Path -Path $configRoot -ChildPath 'speed-test-catalog.json'
Write-Utf8JsonFile -Path $probeConfigPath -Value $probeConfig
Write-Utf8JsonFile -Path $speedConfigPath -Value $speedConfig

$resolvedSpeedTestCliSourcePath = Resolve-SpeedTestCliSeedPath -RequestedSourcePath $SpeedTestCliSourcePath -InstallRoot $InstallRoot
$installedSpeedTestCliPath = Install-SpeedTestCli -ResolvedSourcePath $resolvedSpeedTestCliSourcePath -InstallRoot $InstallRoot

$setTokenScriptPath = Get-FullPathFromBase -BasePath $currentRoot -ChildPath 'scripts\set-influx-token.ps1'
$credentialFilePath = Set-InfluxTokenIfNeeded -SetTokenScriptPath $setTokenScriptPath -ConfigPath $probeConfigPath -InfluxToken $InfluxToken -NonInteractive:$NonInteractive -Force:$Force

$httpValidatorPath = Get-FullPathFromBase -BasePath $currentRoot -ChildPath 'scripts\validate-qoe-probe.ps1'
$speedValidatorPath = Get-FullPathFromBase -BasePath $currentRoot -ChildPath 'scripts\validate-qoe-speed-test.ps1'
$httpProbeScriptPath = Get-FullPathFromBase -BasePath $currentRoot -ChildPath 'scripts\qoe-probe.ps1'
$speedProbeScriptPath = Get-FullPathFromBase -BasePath $currentRoot -ChildPath 'scripts\qoe-speed-test.ps1'

$httpValidation = $null
$speedValidation = $null
if (-not $SkipValidation) {
    $httpValidation = Invoke-ValidationScript -ScriptPath $httpValidatorPath -ProbeScriptPath $httpProbeScriptPath -ConfigPath $probeConfigPath
    Assert-ValidationResult -ValidationResult $httpValidation -Label 'HTTP bootstrap'

    $speedValidation = Invoke-ValidationScript -ScriptPath $speedValidatorPath -ProbeScriptPath $speedProbeScriptPath -ConfigPath $speedConfigPath
    Assert-ValidationResult -ValidationResult $speedValidation -Label 'Speed-test bootstrap'
}

$httpDryRunReportPath = Join-Path -Path $reportsRoot -ChildPath 'http-dry-run.json'
$speedDryRunReportPath = Join-Path -Path $reportsRoot -ChildPath 'speed-test-dry-run.json'
if (-not $SkipDryRun) {
    Invoke-DryRunScript -ScriptPath $httpProbeScriptPath -ConfigPath $probeConfigPath -ReportPath $httpDryRunReportPath | Out-Null
    Invoke-DryRunScript -ScriptPath $speedProbeScriptPath -ConfigPath $speedConfigPath -ReportPath $speedDryRunReportPath | Out-Null
}

$taskOutputs = New-Object System.Collections.Generic.List[string]
if (-not $SkipTaskRegistration) {
    $registerTaskScriptPath = Get-FullPathFromBase -BasePath $currentRoot -ChildPath 'scripts\register-qoe-task.ps1'
    $httpTaskResult = & $registerTaskScriptPath -TaskName 'CX-Radar-QoE-Probe' -ScriptPath $httpProbeScriptPath -ConfigPath $probeConfigPath -IntervalMinutes 5 -RunAsCurrentUser -TaskDescription 'Runs the CX-Radar QoE HTTP probe and sends metrics to InfluxDB Cloud.'
    $speedTaskResult = & $registerTaskScriptPath -TaskName 'CX-Radar-QoE-SpeedTest' -ScriptPath $speedProbeScriptPath -ConfigPath $speedConfigPath -IntervalMinutes 30 -RunAsCurrentUser -TaskDescription 'Runs the CX-Radar QoE speed-test probe and sends metrics to InfluxDB Cloud.'
    $taskOutputs.Add([string]$httpTaskResult)
    $taskOutputs.Add([string]$speedTaskResult)
}

Write-Utf8JsonFile -Path $statePath -Value $state

[pscustomobject]@{
    HubName = [string]$state.hubName
    Site = [string]$state.site
    ProbeId = [string]$state.probeId
    InstallationId = [string]$state.installationId
    InstallRoot = $InstallRoot
    CurrentRoot = $currentRoot
    StatePath = $statePath
    ProbeConfigPath = $probeConfigPath
    SpeedTestConfigPath = $speedConfigPath
    InfluxCredentialFilePath = $credentialFilePath
    SpeedTestCliPath = $installedSpeedTestCliPath
    ValidationSkipped = [bool]$SkipValidation
    DryRunSkipped = [bool]$SkipDryRun
    TaskRegistrationSkipped = [bool]$SkipTaskRegistration
    HttpValidation = $httpValidation
    SpeedValidation = $speedValidation
    TaskOutputs = @($taskOutputs)
}