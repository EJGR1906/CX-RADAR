[CmdletBinding()]
param(
    [Parameter()]
    [string]$ProbeScriptPath = '',

    [Parameter()]
    [string]$ValidateScriptPath = '',

    [Parameter()]
    [string]$ConfigPath = '',

    [Parameter()]
    [string]$OutputPath = '',

    [Parameter()]
    [ValidateRange(10, 600)]
    [int]$MaxProbeRuntimeSeconds = 120,

    [Parameter()]
    [switch]$RunResilienceChecks,

    [Parameter()]
    [switch]$IncludeTlsScenario
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

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $directory = Split-Path -Path $Path -Parent
    if (-not [string]::IsNullOrWhiteSpace($directory) -and -not (Test-Path -Path $directory -PathType Container)) {
        New-Item -Path $directory -ItemType Directory -Force | Out-Null
    }

    $json = $Value | ConvertTo-Json -Depth 8
    $utf8Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json, $utf8Encoding)
}

function New-DeepCopyObject {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    return ($Value | ConvertTo-Json -Depth 12 | ConvertFrom-Json)
}

function ConvertTo-InvariantDouble {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $normalized = $Value.Replace(',', '.')
    return [double]::Parse($normalized, [System.Globalization.CultureInfo]::InvariantCulture)
}

function Get-CurlProcessIds {
    $processes = @(Get-Process -Name 'curl' -ErrorAction SilentlyContinue)
    return @($processes | ForEach-Object { $_.Id })
}

function Get-ScenarioLogPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedConfigPath,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config,

        [Parameter(Mandatory = $true)]
        [datetime]$RunDate
    )

    $logDirectory = Join-Path -Path (Split-Path -Path $ResolvedConfigPath -Parent) -ChildPath "..\$($Config.probeRun.logDirectory)"
    $resolvedLogDirectory = [System.IO.Path]::GetFullPath($logDirectory)
    $logFileName = 'qoe-probe-{0}.log' -f $RunDate.ToString('yyyy-MM-dd')
    return Join-Path -Path $resolvedLogDirectory -ChildPath $logFileName
}

function ConvertFrom-ProbeLog {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Lines
    )

    $targetResults = @()
    $summary = $null
    $warningCount = 0
    $errorCount = 0
    $normalizedLines = @($Lines | ForEach-Object { [string]$_ })

    foreach ($line in $normalizedLines) {
        if ($line -match 'Target (?<service>[^/]+)/(?<endpoint>[^ ]+) completed with HTTP (?<http>\d+), curl exit (?<exit>-?\d+), total (?<total>[\d\.,]+) ms') {
            $targetResults += [pscustomobject]@{
                service = [string]$matches.service
                endpoint_name = [string]$matches.endpoint
                http_status = [int]$matches.http
                curl_exit_code = [int]$matches.exit
                time_total_ms = ConvertTo-InvariantDouble -Value ([string]$matches.total)
            }
            continue
        }

        if ($line -match 'QoE probe finished\. Success=(?<success>\d+), Failure=(?<failure>\d+), Duration=(?<duration>[\d\.,]+) ms') {
            $summary = [pscustomobject]@{
                success_count = [int]$matches.success
                failure_count = [int]$matches.failure
                run_duration_ms = ConvertTo-InvariantDouble -Value ([string]$matches.duration)
            }
            continue
        }

        if ($line -match '\[WARN\]') {
            $warningCount++
            continue
        }

        if ($line -match '\[ERROR\]') {
            $errorCount++
        }
    }

    return [pscustomobject]@{
        target_results = @($targetResults)
        summary = $summary
        warning_count = [int]$warningCount
        error_count = [int]$errorCount
        line_count = [int]$normalizedLines.Count
    }
}

function Invoke-ProbeProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProbeScriptPath,

        [Parameter(Mandatory = $true)]
        [string]$ConfigPath,

        [Parameter(Mandatory = $true)]
        [bool]$SkipInfluxWrite,

        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds,

        [Parameter()]
        [hashtable]$EnvironmentOverrides = @{}
    )

    $processStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processStartInfo.FileName = Join-Path -Path $PSHOME -ChildPath 'powershell.exe'
    $processStartInfo.UseShellExecute = $false
    $processStartInfo.RedirectStandardOutput = $true
    $processStartInfo.RedirectStandardError = $true
    $processStartInfo.CreateNoWindow = $true

    $arguments = New-Object System.Collections.Generic.List[string]
    foreach ($value in @(
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy', 'RemoteSigned',
        '-File', ('"{0}"' -f $ProbeScriptPath),
        '-ConfigPath', ('"{0}"' -f $ConfigPath)
    )) {
        $arguments.Add([string]$value)
    }

    if ($SkipInfluxWrite) {
        $arguments.Add('-SkipInfluxWrite')
    }

    $processStartInfo.Arguments = $arguments -join ' '

    foreach ($key in $EnvironmentOverrides.Keys) {
        $processStartInfo.EnvironmentVariables[$key] = [string]$EnvironmentOverrides[$key]
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $processStartInfo

    $startTime = Get-Date
    $null = $process.Start()

    $timedOut = -not $process.WaitForExit($TimeoutSeconds * 1000)
    if ($timedOut) {
        try {
            $process.Kill()
        }
        catch {
        }
    }
    else {
        $process.WaitForExit()
    }

    $durationMs = [math]::Round(((Get-Date) - $startTime).TotalMilliseconds, 2)
    $standardOutput = $process.StandardOutput.ReadToEnd().Trim()
    $standardError = $process.StandardError.ReadToEnd().Trim()
    $exitCode = -1
    if (-not $timedOut) {
        $exitCode = [int]$process.ExitCode
    }

    return [pscustomobject]@{
        timed_out = [bool]$timedOut
        exit_code = [int]$exitCode
        duration_ms = [double]$durationMs
        stdout = [string]$standardOutput
        stderr = [string]$standardError
    }
}

function New-ScenarioConfig {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$BaseConfig,

        [Parameter(Mandatory = $true)]
        [string]$ScenarioRoot,

        [Parameter(Mandatory = $true)]
        [string]$ScenarioName,

        [Parameter(Mandatory = $true)]
        [object[]]$Targets,

        [Parameter()]
        [hashtable]$ProbeRunOverrides = @{},

        [Parameter()]
        [hashtable]$InfluxOverrides = @{}
    )

    $scenarioDirectory = Join-Path -Path $ScenarioRoot -ChildPath $ScenarioName
    if (-not (Test-Path -Path $scenarioDirectory -PathType Container)) {
        New-Item -Path $scenarioDirectory -ItemType Directory -Force | Out-Null
    }

    $scenarioConfig = New-DeepCopyObject -Value $BaseConfig
    $scenarioConfig.probe.probeId = '{0}-qa-{1}' -f [string]$BaseConfig.probe.probeId, $ScenarioName
    $scenarioConfig.probeRun.startJitterSecondsMax = 0
    $scenarioConfig.probeRun.targetDelayMilliseconds = 0
    $scenarioConfig.probeRun.retryCount = 0
    $scenarioConfig.probeRun.retryDelaySeconds = 0
    $scenarioConfig.probeRun.logDirectory = 'logs\{0}' -f $ScenarioName

    foreach ($propertyName in $ProbeRunOverrides.Keys) {
        $scenarioConfig.probeRun.$propertyName = $ProbeRunOverrides[$propertyName]
    }

    foreach ($propertyName in $InfluxOverrides.Keys) {
        $scenarioConfig.influx.$propertyName = $InfluxOverrides[$propertyName]
    }

    $scenarioConfig.targets = @($Targets)

    $scenarioConfigPath = Join-Path -Path $scenarioDirectory -ChildPath 'probe-catalog.json'
    Write-JsonFile -Path $scenarioConfigPath -Value $scenarioConfig

    return $scenarioConfigPath
}

function Test-LogCoverage {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$ParsedLog,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedTargetCount
    )

    if ($null -eq $ParsedLog.summary) {
        return $false
    }

    return ($ParsedLog.target_results.Count -eq $ExpectedTargetCount -and $ParsedLog.line_count -ge ($ExpectedTargetCount + 3))
}

function Get-ParsedLogFailureCount {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$ParsedLog
    )

    if ($null -eq $ParsedLog.summary) {
        return -1
    }

    return [int]$ParsedLog.summary.failure_count
}

function Invoke-SmokeCertification {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProbeScriptPath,

        [Parameter(Mandatory = $true)]
        [string]$ScenarioConfigPath,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ScenarioConfig,

        [Parameter(Mandatory = $true)]
        [int]$MaxProbeRuntimeSeconds
    )

    $resolvedScenarioConfigPath = [System.IO.Path]::GetFullPath((Resolve-Path -Path $ScenarioConfigPath).Path)
    $scenarioLogPath = Get-ScenarioLogPath -ResolvedConfigPath $resolvedScenarioConfigPath -Config $ScenarioConfig -RunDate (Get-Date)
    $beforeCurlIds = @(Get-CurlProcessIds)
    $processResult = Invoke-ProbeProcess -ProbeScriptPath $ProbeScriptPath -ConfigPath $resolvedScenarioConfigPath -SkipInfluxWrite $true -TimeoutSeconds $MaxProbeRuntimeSeconds
    $afterCurlIds = @(Get-CurlProcessIds)
    $newCurlIds = @($afterCurlIds | Where-Object { $beforeCurlIds -notcontains $_ })
    if (Test-Path -Path $scenarioLogPath -PathType Leaf) {
        $logLines = @(Get-Content -Path $scenarioLogPath)
    }
    else {
        $logLines = @()
    }
    $parsedLog = ConvertFrom-ProbeLog -Lines $logLines
    $latencyValues = @($parsedLog.target_results | ForEach-Object { [double]$_.time_total_ms })

    return [pscustomobject]@{
        name = 'smoke'
        passed = [bool](
            -not $processResult.timed_out -and
            $processResult.exit_code -eq 0 -and
            $newCurlIds.Count -eq 0 -and
            (Test-LogCoverage -ParsedLog $parsedLog -ExpectedTargetCount ([int](@($ScenarioConfig.targets).Count))) -and
            $latencyValues.Count -gt 0 -and
            (@($latencyValues | Where-Object { $_ -gt 0 }).Count -gt 0)
        )
        process = $processResult
        new_curl_process_ids = @($newCurlIds)
        parsed_log = $parsedLog
        distinct_latency_values = [int](@($latencyValues | Select-Object -Unique).Count)
    }
}

function Invoke-ResilienceScenario {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$ProbeScriptPath,

        [Parameter(Mandatory = $true)]
        [string]$ScenarioConfigPath,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ScenarioConfig,

        [Parameter(Mandatory = $true)]
        [int]$MaxProbeRuntimeSeconds,

        [Parameter(Mandatory = $true)]
        [bool]$SkipInfluxWrite,

        [Parameter(Mandatory = $true)]
        [scriptblock]$PassCondition,

        [Parameter()]
        [hashtable]$EnvironmentOverrides = @{}
    )

    $resolvedScenarioConfigPath = [System.IO.Path]::GetFullPath((Resolve-Path -Path $ScenarioConfigPath).Path)
    $scenarioLogPath = Get-ScenarioLogPath -ResolvedConfigPath $resolvedScenarioConfigPath -Config $ScenarioConfig -RunDate (Get-Date)
    $beforeCurlIds = @(Get-CurlProcessIds)
    $processResult = Invoke-ProbeProcess -ProbeScriptPath $ProbeScriptPath -ConfigPath $resolvedScenarioConfigPath -SkipInfluxWrite $SkipInfluxWrite -TimeoutSeconds $MaxProbeRuntimeSeconds -EnvironmentOverrides $EnvironmentOverrides
    $afterCurlIds = @(Get-CurlProcessIds)
    $newCurlIds = @($afterCurlIds | Where-Object { $beforeCurlIds -notcontains $_ })
    if (Test-Path -Path $scenarioLogPath -PathType Leaf) {
        $logLines = @(Get-Content -Path $scenarioLogPath)
    }
    else {
        $logLines = @()
    }
    $parsedLog = ConvertFrom-ProbeLog -Lines $logLines
    $result = [pscustomobject]@{
        name = [string]$Name
        process = $processResult
        parsed_log = $parsedLog
        new_curl_process_ids = @($newCurlIds)
    }

    $passed = & $PassCondition $result
    return [pscustomobject]@{
        name = [string]$Name
        passed = [bool]$passed
        process = $processResult
        parsed_log = $parsedLog
        new_curl_process_ids = @($newCurlIds)
    }
}

$scriptBasePath = Get-ScriptBasePath
if ([string]::IsNullOrWhiteSpace($ProbeScriptPath)) {
    $ProbeScriptPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath 'qoe-probe.ps1'
}

if ([string]::IsNullOrWhiteSpace($ValidateScriptPath)) {
    $ValidateScriptPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath 'validate-qoe-probe.ps1'
}

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\config\probe-catalog.json'
}

$resolvedProbeScriptPath = [System.IO.Path]::GetFullPath((Resolve-Path -Path $ProbeScriptPath).Path)
$resolvedValidateScriptPath = [System.IO.Path]::GetFullPath((Resolve-Path -Path $ValidateScriptPath).Path)
$resolvedConfigPath = [System.IO.Path]::GetFullPath((Resolve-Path -Path $ConfigPath).Path)

$baseConfig = Get-Content -Path $resolvedConfigPath -Raw | ConvertFrom-Json
$enabledTargets = @($baseConfig.targets | Where-Object { $_.enabled })
$scenarioRoot = Join-Path -Path $env:TEMP -ChildPath ('cx-radar-qa-{0}' -f ([guid]::NewGuid().ToString('N')))
New-Item -Path $scenarioRoot -ItemType Directory -Force | Out-Null

$validateResult = & $resolvedValidateScriptPath -ProbeScriptPath $resolvedProbeScriptPath -ConfigPath $resolvedConfigPath

$smokeConfigPath = New-ScenarioConfig -BaseConfig $baseConfig -ScenarioRoot $scenarioRoot -ScenarioName 'smoke' -Targets $enabledTargets -ProbeRunOverrides @{
    connectTimeoutSeconds = 5
    maxTimeSeconds = 20
}
$smokeConfig = Get-Content -Path $smokeConfigPath -Raw | ConvertFrom-Json
$smokeResult = Invoke-SmokeCertification -ProbeScriptPath $resolvedProbeScriptPath -ScenarioConfigPath $smokeConfigPath -ScenarioConfig $smokeConfig -MaxProbeRuntimeSeconds $MaxProbeRuntimeSeconds

$resilienceResults = @()

if ($RunResilienceChecks) {
    $dnsConfigPath = New-ScenarioConfig -BaseConfig $baseConfig -ScenarioRoot $scenarioRoot -ScenarioName 'dns-failure' -Targets @([
        pscustomobject]@{
            service = 'qa'
            endpointName = 'dns-failure'
            url = 'https://cx-radar-probe-test.invalid/'
            method = 'GET'
            expectedHttpCodes = @(200)
            enabled = $true
        }
    ) -ProbeRunOverrides @{
        connectTimeoutSeconds = 2
        maxTimeSeconds = 6
    }
    $dnsConfig = Get-Content -Path $dnsConfigPath -Raw | ConvertFrom-Json
    $resilienceResults += (Invoke-ResilienceScenario -Name 'dns_failure' -ProbeScriptPath $resolvedProbeScriptPath -ScenarioConfigPath $dnsConfigPath -ScenarioConfig $dnsConfig -MaxProbeRuntimeSeconds $MaxProbeRuntimeSeconds -SkipInfluxWrite $true -PassCondition {
        param($ScenarioResult)
        return (
            -not $ScenarioResult.process.timed_out -and
            $ScenarioResult.process.exit_code -eq 0 -and
            $ScenarioResult.new_curl_process_ids.Count -eq 0 -and
            (Get-ParsedLogFailureCount -ParsedLog $ScenarioResult.parsed_log) -ge 1
        )
    })

    $timeoutConfigPath = New-ScenarioConfig -BaseConfig $baseConfig -ScenarioRoot $scenarioRoot -ScenarioName 'timeout' -Targets @([
        pscustomobject]@{
            service = 'qa'
            endpointName = 'timeout'
            url = 'http://10.255.255.1/'
            method = 'GET'
            expectedHttpCodes = @(200)
            enabled = $true
        }
    ) -ProbeRunOverrides @{
        connectTimeoutSeconds = 1
        maxTimeSeconds = 4
    }
    $timeoutConfig = Get-Content -Path $timeoutConfigPath -Raw | ConvertFrom-Json
    $resilienceResults += (Invoke-ResilienceScenario -Name 'timeout_bound' -ProbeScriptPath $resolvedProbeScriptPath -ScenarioConfigPath $timeoutConfigPath -ScenarioConfig $timeoutConfig -MaxProbeRuntimeSeconds $MaxProbeRuntimeSeconds -SkipInfluxWrite $true -PassCondition {
        param($ScenarioResult)
        return (
            -not $ScenarioResult.process.timed_out -and
            $ScenarioResult.process.duration_ms -le 15000 -and
            $ScenarioResult.new_curl_process_ids.Count -eq 0 -and
            (Get-ParsedLogFailureCount -ParsedLog $ScenarioResult.parsed_log) -ge 1
        )
    })

    $influxOutageConfigPath = New-ScenarioConfig -BaseConfig $baseConfig -ScenarioRoot $scenarioRoot -ScenarioName 'influx-outage' -Targets @([
        pscustomobject]@{
            service = 'qa'
            endpointName = 'influx-outage'
            url = 'https://cx-radar-probe-test.invalid/'
            method = 'GET'
            expectedHttpCodes = @(200)
            enabled = $true
        }
    ) -ProbeRunOverrides @{
        connectTimeoutSeconds = 2
        maxTimeSeconds = 6
    } -InfluxOverrides @{
        baseUrl = 'http://127.0.0.1:1'
    }
    $influxOutageConfig = Get-Content -Path $influxOutageConfigPath -Raw | ConvertFrom-Json
    $dummyTokenName = [string]$influxOutageConfig.influx.tokenEnvVar
    $resilienceResults += (Invoke-ResilienceScenario -Name 'influx_outage' -ProbeScriptPath $resolvedProbeScriptPath -ScenarioConfigPath $influxOutageConfigPath -ScenarioConfig $influxOutageConfig -MaxProbeRuntimeSeconds $MaxProbeRuntimeSeconds -SkipInfluxWrite $false -EnvironmentOverrides @{ $dummyTokenName = 'dummy-token' } -PassCondition {
        param($ScenarioResult)
        return (
            -not $ScenarioResult.process.timed_out -and
            $ScenarioResult.process.exit_code -ne 0 -and
            $ScenarioResult.new_curl_process_ids.Count -eq 0 -and
            $ScenarioResult.parsed_log.error_count -ge 1
        )
    })

    if ($IncludeTlsScenario) {
        $tlsConfigPath = New-ScenarioConfig -BaseConfig $baseConfig -ScenarioRoot $scenarioRoot -ScenarioName 'tls-failure' -Targets @([
            pscustomobject]@{
                service = 'qa'
                endpointName = 'tls-failure'
                url = 'https://expired.badssl.com/'
                method = 'GET'
                expectedHttpCodes = @(200)
                enabled = $true
            }
        ) -ProbeRunOverrides @{
            connectTimeoutSeconds = 5
            maxTimeSeconds = 15
        }
        $tlsConfig = Get-Content -Path $tlsConfigPath -Raw | ConvertFrom-Json
        $resilienceResults += (Invoke-ResilienceScenario -Name 'tls_failure' -ProbeScriptPath $resolvedProbeScriptPath -ScenarioConfigPath $tlsConfigPath -ScenarioConfig $tlsConfig -MaxProbeRuntimeSeconds $MaxProbeRuntimeSeconds -SkipInfluxWrite $true -PassCondition {
            param($ScenarioResult)
            return (
                -not $ScenarioResult.process.timed_out -and
                $ScenarioResult.new_curl_process_ids.Count -eq 0 -and
                (Get-ParsedLogFailureCount -ParsedLog $ScenarioResult.parsed_log) -ge 1
            )
        })
    }
}

$failedResilienceResults = @($resilienceResults | Where-Object { -not $_.passed })

$summary = [pscustomobject]@{
    started_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    scenario_root = $scenarioRoot
    validate = $validateResult
    smoke = $smokeResult
    resilience = @($resilienceResults)
    overall_passed = [bool](
        $validateResult.ProbeScriptSyntax -eq 'OK' -and
        $validateResult.ConfigFile -eq 'OK' -and
        $validateResult.CurlAvailable -and
        $smokeResult.passed -and
        ($failedResilienceResults.Count -eq 0)
    )
}

if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    $resolvedOutputPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath $OutputPath
    Write-JsonFile -Path $resolvedOutputPath -Value $summary
}

[pscustomobject]$summary