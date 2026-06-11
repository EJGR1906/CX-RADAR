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

function Get-OptionalStringValue {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Source,

        [Parameter(Mandatory = $true)]
        [string]$PropertyName,

        [Parameter()]
        [string]$DefaultValue = ''
    )

    if ($null -ne $Source -and $Source.PSObject.Properties.Name -contains $PropertyName -and $null -ne $Source.$PropertyName -and -not [string]::IsNullOrWhiteSpace([string]$Source.$PropertyName)) {
        return [string]$Source.$PropertyName
    }

    return $DefaultValue
}

function Get-TargetType {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target
    )

    return (Get-OptionalStringValue -Source $Target -PropertyName 'type' -DefaultValue 'http').ToLowerInvariant()
}

function Get-PortableToolProperty {
    param(
        [AllowNull()]
        [object]$PortableToolsConfig,

        [Parameter(Mandatory = $true)]
        [string]$PropertyName,

        [Parameter(Mandatory = $true)]
        [string]$DefaultValue
    )

    if ($null -ne $PortableToolsConfig -and $PortableToolsConfig.PSObject.Properties.Name -contains $PropertyName -and -not [string]::IsNullOrWhiteSpace([string]$PortableToolsConfig.$PropertyName)) {
        return [string]$PortableToolsConfig.$PropertyName
    }

    return $DefaultValue
}

function Get-ProbePortableTools {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun,

        [Parameter(Mandatory = $true)]
        [string]$ScriptBasePath
    )

    $repoRoot = Get-FullPathFromBase -BasePath $ScriptBasePath -ChildPath '..'
    $portableToolsConfig = if ($ProbeRun.PSObject.Properties.Name -contains 'portableTools') { $ProbeRun.portableTools } else { $null }
    $networkQualityDefaultPath = Join-Path -Path $env:SystemRoot -ChildPath 'System32\networkquality.exe'

    return [pscustomobject]@{
        RepoRoot = [System.IO.Path]::GetFullPath($repoRoot)
        NodeExe = Get-FullPathFromBase -BasePath $repoRoot -ChildPath (Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'nodeExe' -DefaultValue 'bin\node\node.exe')
        FastCliScript = Get-FullPathFromBase -BasePath $repoRoot -ChildPath (Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'fastCliScript' -DefaultValue 'bin\fast-cli\node_modules\fast-cli\distribution\cli.js')
        YtDlpExe = Get-FullPathFromBase -BasePath $repoRoot -ChildPath (Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'ytDlpExe' -DefaultValue 'bin\yt-dlp.exe')
        NetworkQualityExe = Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'networkQualityExe' -DefaultValue $networkQualityDefaultPath
    }
}

function Test-CurlAvailability {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $portableCurlPath = Get-FullPathFromBase -BasePath $RepoRoot -ChildPath 'bin\curl.exe'
    if (Test-Path -Path $portableCurlPath -PathType Leaf) {
        return $true
    }

    $systemCurlPath = Join-Path -Path $env:SystemRoot -ChildPath 'System32\curl.exe'
    if (Test-Path -Path $systemCurlPath -PathType Leaf) {
        return $true
    }

    return [bool](Get-Command -Name 'curl.exe' -ErrorAction SilentlyContinue)
}

function Test-ConfiguredPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter()]
        [string]$CandidatePath
    )

    if ([string]::IsNullOrWhiteSpace($CandidatePath)) {
        return $false
    }

    if ([System.IO.Path]::IsPathRooted($CandidatePath)) {
        return (Test-Path -Path $CandidatePath -PathType Leaf)
    }

    $resolvedPath = Get-FullPathFromBase -BasePath $RepoRoot -ChildPath $CandidatePath
    return (Test-Path -Path $resolvedPath -PathType Leaf)
}

function Test-NetworkQualityAvailabilityForTarget {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    $configuredPath = Get-OptionalStringValue -Source $Target -PropertyName 'commandPath' -DefaultValue $PortableTools.NetworkQualityExe
    return (Test-ConfiguredPath -RepoRoot $PortableTools.RepoRoot -CandidatePath $configuredPath)
}

function Test-SpeedTargetFallbackReady {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target
    )

    $downloadUrl = Get-OptionalStringValue -Source $Target -PropertyName 'downloadUrl' -DefaultValue (Get-OptionalStringValue -Source $Target -PropertyName 'url' -DefaultValue '')
    return -not [string]::IsNullOrWhiteSpace($downloadUrl)
}

function Get-UploadMeasurementMethod {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun
    )

    $targetUploadMethod = Get-OptionalStringValue -Source $Target -PropertyName 'uploadMeasurementMethod' -DefaultValue ''
    if (-not [string]::IsNullOrWhiteSpace($targetUploadMethod)) {
        return $targetUploadMethod.ToLowerInvariant()
    }

    return (Get-OptionalStringValue -Source $ProbeRun -PropertyName 'defaultUploadMeasurementMethod' -DefaultValue 'none').ToLowerInvariant()
}

function Test-UploadUrlMeasurementReady {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target
    )

    return -not [string]::IsNullOrWhiteSpace((Get-OptionalStringValue -Source $Target -PropertyName 'uploadUrl' -DefaultValue ''))
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
        if (-not $target.enabled) {
            continue
        }

        if ([string]::IsNullOrWhiteSpace([string]$target.service)) {
            $issues.Add('Enabled target is missing service.')
        }

        if ([string]::IsNullOrWhiteSpace([string]$target.endpointName)) {
            $issues.Add("Target '$($target.service)' is enabled but has no endpointName.")
        }

        $targetType = Get-TargetType -Target $target
        switch ($targetType) {
            'http' {
                if ([string]::IsNullOrWhiteSpace([string]$target.url)) {
                    $issues.Add("HTTP target '$($target.service)/$($target.endpointName)' is enabled but has no URL.")
                }

                break
            }
            'speedtest' {
                $speedTestMethod = (Get-OptionalStringValue -Source $target -PropertyName 'speedTestMethod' -DefaultValue '').ToLowerInvariant()
                if ([string]::IsNullOrWhiteSpace($speedTestMethod)) {
                    $issues.Add("Speed-test target '$($target.service)/$($target.endpointName)' is missing speedTestMethod.")
                    break
                }

                switch ($speedTestMethod) {
                    'fast-cli' {
                        break
                    }
                    'yt-dlp' {
                        $videoUrl = Get-OptionalStringValue -Source $target -PropertyName 'videoUrl' -DefaultValue (Get-OptionalStringValue -Source $target -PropertyName 'url' -DefaultValue '')
                        if ([string]::IsNullOrWhiteSpace($videoUrl)) {
                            $issues.Add("yt-dlp target '$($target.service)/$($target.endpointName)' requires videoUrl or url.")
                        }

                        break
                    }
                    'networkquality' {
                        if (-not (Test-SpeedTargetFallbackReady -Target $target) -and [string]::IsNullOrWhiteSpace((Get-OptionalStringValue -Source $target -PropertyName 'commandPath' -DefaultValue ''))) {
                            $issues.Add("networkquality target '$($target.service)/$($target.endpointName)' requires downloadUrl/url for burst fallback or an explicit commandPath.")
                        }

                        break
                    }
                    'burst' {
                        if (-not (Test-SpeedTargetFallbackReady -Target $target)) {
                            $issues.Add("Burst target '$($target.service)/$($target.endpointName)' requires downloadUrl or url.")
                        }

                        break
                    }
                    default {
                        $issues.Add("Target '$($target.service)/$($target.endpointName)' uses unsupported speedTestMethod '$speedTestMethod'.")
                    }
                }

                $uploadMeasurementMethod = Get-UploadMeasurementMethod -Target $target -ProbeRun $Config.probeRun
                switch ($uploadMeasurementMethod) {
                    'none' {
                        break
                    }
                    'networkquality' {
                        break
                    }
                    'curl-upload' {
                        break
                    }
                    'upload-url' {
                        if (-not (Test-UploadUrlMeasurementReady -Target $target)) {
                            $issues.Add("Target '$($target.service)/$($target.endpointName)' requires uploadUrl when uploadMeasurementMethod is 'upload-url'.")
                        }

                        break
                    }
                    default {
                        $issues.Add("Target '$($target.service)/$($target.endpointName)' uses unsupported uploadMeasurementMethod '$uploadMeasurementMethod'.")
                    }
                }

                break
            }
            default {
                $issues.Add("Target '$($target.service)/$($target.endpointName)' uses unsupported type '$targetType'.")
            }
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
$repoRoot = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..'
$portableTools = Get-ProbePortableTools -ProbeRun $config.probeRun -ScriptBasePath $scriptBasePath
$enabledTargets = @($config.targets | Where-Object { $_.enabled })
$enabledHttpTargets = @($enabledTargets | Where-Object { (Get-TargetType -Target $_) -eq 'http' })
$enabledSpeedTargets = @($enabledTargets | Where-Object { (Get-TargetType -Target $_) -eq 'speedtest' })
$fastCliTargets = @($enabledSpeedTargets | Where-Object { (Get-OptionalStringValue -Source $_ -PropertyName 'speedTestMethod' -DefaultValue '').ToLowerInvariant() -eq 'fast-cli' })
$ytDlpTargets = @($enabledSpeedTargets | Where-Object { (Get-OptionalStringValue -Source $_ -PropertyName 'speedTestMethod' -DefaultValue '').ToLowerInvariant() -eq 'yt-dlp' })
$networkQualityTargets = @($enabledSpeedTargets | Where-Object { (Get-OptionalStringValue -Source $_ -PropertyName 'speedTestMethod' -DefaultValue '').ToLowerInvariant() -eq 'networkquality' })
$burstTargets = @($enabledSpeedTargets | Where-Object { (Get-OptionalStringValue -Source $_ -PropertyName 'speedTestMethod' -DefaultValue '').ToLowerInvariant() -eq 'burst' })
$uploadMeasurementNetworkQualityTargets = @($enabledSpeedTargets | Where-Object { (Get-UploadMeasurementMethod -Target $_ -ProbeRun $config.probeRun) -eq 'networkquality' })
$uploadMeasurementUploadUrlTargets = @($enabledSpeedTargets | Where-Object { (Get-UploadMeasurementMethod -Target $_ -ProbeRun $config.probeRun) -eq 'upload-url' })
$uploadMeasurementCurlUploadTargets = @($enabledSpeedTargets | Where-Object { (Get-UploadMeasurementMethod -Target $_ -ProbeRun $config.probeRun) -eq 'curl-upload' })
$curlAvailable = if ($enabledHttpTargets.Count -gt 0) { Test-CurlAvailability -RepoRoot $repoRoot } else { $true }
$portableNodeAvailable = if ($fastCliTargets.Count -gt 0) { (Test-Path -Path $portableTools.NodeExe -PathType Leaf) } else { $true }
$fastCliAvailable = if ($fastCliTargets.Count -gt 0) { (Test-Path -Path $portableTools.FastCliScript -PathType Leaf) } else { $true }
$ytDlpAvailable = if ($ytDlpTargets.Count -gt 0) { (Test-Path -Path $portableTools.YtDlpExe -PathType Leaf) } else { $true }
$allNetworkQualityTargets = @($networkQualityTargets + $uploadMeasurementNetworkQualityTargets)
$networkQualityCommandAvailable = if ($allNetworkQualityTargets.Count -gt 0) { @($allNetworkQualityTargets | Where-Object { Test-NetworkQualityAvailabilityForTarget -Target $_ -PortableTools $portableTools }).Count -eq $allNetworkQualityTargets.Count } else { $true }
$networkQualityFallbackReady = if ($networkQualityTargets.Count -gt 0) { @($networkQualityTargets | Where-Object { Test-SpeedTargetFallbackReady -Target $_ }).Count -eq $networkQualityTargets.Count } else { $true }
$burstTargetsReady = if ($burstTargets.Count -gt 0) { @($burstTargets | Where-Object { Test-SpeedTargetFallbackReady -Target $_ }).Count -eq $burstTargets.Count } else { $true }
$uploadUrlTargetsReady = if ($uploadMeasurementUploadUrlTargets.Count -gt 0) { @($uploadMeasurementUploadUrlTargets | Where-Object { Test-UploadUrlMeasurementReady -Target $_ }).Count -eq $uploadMeasurementUploadUrlTargets.Count } else { $true }
$curlUploadTargetsReady = $true
$uploadMeasurementNetworkQualityReady = if ($uploadMeasurementNetworkQualityTargets.Count -gt 0) { $networkQualityCommandAvailable } else { $true }
$uploadMeasurementTargetsReady = ($uploadMeasurementNetworkQualityReady -and $uploadUrlTargetsReady -and $curlUploadTargetsReady)
$probeIspConfigured = if ($enabledSpeedTargets.Count -gt 0) { -not [string]::IsNullOrWhiteSpace((Get-OptionalStringValue -Source $config.probe -PropertyName 'isp' -DefaultValue '')) } else { $true }
$speedTestTargetsReady = ($portableNodeAvailable -and $fastCliAvailable -and $ytDlpAvailable -and ($networkQualityCommandAvailable -or $networkQualityFallbackReady) -and $burstTargetsReady -and $uploadUrlTargetsReady -and $curlUploadTargetsReady)

$results = [ordered]@{
    ProbeScriptSyntax = 'OK'
    ConfigFile = 'OK'
    CurlAvailable = [bool]$curlAvailable
    PortableNodeAvailable = [bool]$portableNodeAvailable
    FastCliAvailable = [bool]$fastCliAvailable
    YtDlpAvailable = [bool]$ytDlpAvailable
    NetworkQualityCommandAvailable = [bool]$networkQualityCommandAvailable
    NetworkQualityFallbackReady = [bool]$networkQualityFallbackReady
    BurstTargetsReady = [bool]$burstTargetsReady
    UploadUrlTargetsReady = [bool]$uploadUrlTargetsReady
    CurlUploadTargetsReady = [bool]$curlUploadTargetsReady
    UploadMeasurementTargetsReady = [bool]$uploadMeasurementTargetsReady
    ProbeIspConfigured = [bool]$probeIspConfigured
    SpeedTestTargetsReady = [bool]$speedTestTargetsReady
    InfluxTokenAvailable = [bool]$tokenStatus.Available
    InfluxTokenSource = [string]$tokenStatus.Source
    InfluxCredentialFilePath = [string]$tokenStatus.CredentialFilePath
    InfluxCredentialFileExists = [bool]$tokenStatus.CredentialFileExists
    EnabledTargets = [int]$enabledTargets.Count
    EnabledHttpTargets = [int]$enabledHttpTargets.Count
    EnabledSpeedTestTargets = [int]$enabledSpeedTargets.Count
}

[pscustomobject]$results