[CmdletBinding()]
param(
    [Parameter()]
    [string]$ConfigPath = '',

    [Parameter()]
    [string]$RunReportPath = '',

    [Parameter()]
    [switch]$SkipInfluxWrite
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

function Write-Log {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,

        [Parameter()]
        [ValidateSet('INFO', 'WARN', 'ERROR')]
        [string]$Level = 'INFO',

        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )

    $timestamp = (Get-Date).ToString('s')
    Add-Content -Path $LogPath -Value "[$timestamp] [$Level] $Message"
}

function Write-RunReport {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Report
    )

    $reportDirectory = Split-Path -Path $Path -Parent
    if (-not [string]::IsNullOrWhiteSpace($reportDirectory) -and -not (Test-Path -Path $reportDirectory -PathType Container)) {
        New-Item -Path $reportDirectory -ItemType Directory -Force | Out-Null
    }

    $jsonReport = $Report | ConvertTo-Json -Depth 8
    $utf8Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $jsonReport, $utf8Encoding)
}

function ConvertTo-EscapedTagValue {
    param(
        [AllowNull()]
        [object]$Value
    )

    if ($null -eq $Value) {
        return ''
    }

    return ($Value.ToString().Replace('\', '\\').Replace(' ', '\ ').Replace(',', '\,').Replace('=', '\='))
}

function ConvertTo-EscapedFieldString {
    param(
        [AllowNull()]
        [object]$Value
    )

    if ($null -eq $Value) {
        return ''
    }

    return ($Value.ToString().Replace('\', '\\').Replace('"', '\"'))
}

function Get-InfluxLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Measurement,

        [Parameter(Mandatory = $true)]
        [hashtable]$Tags,

        [Parameter(Mandatory = $true)]
        [hashtable]$Fields,

        [Parameter(Mandatory = $true)]
        [long]$TimestampMs
    )

    $tagPairs = foreach ($key in ($Tags.Keys | Sort-Object)) {
        $value = $Tags[$key]
        if ([string]::IsNullOrWhiteSpace([string]$value)) {
            continue
        }

        "{0}={1}" -f (ConvertTo-EscapedTagValue -Value $key), (ConvertTo-EscapedTagValue -Value $value)
    }

    $fieldPairs = foreach ($key in ($Fields.Keys | Sort-Object)) {
        $value = $Fields[$key]
        if ($null -eq $value) {
            continue
        }

        $encodedValue = switch ($value.GetType().Name) {
            'Boolean' { if ($value) { 'true' } else { 'false' }; break }
            'Byte' { "{0}i" -f [string]$value; break }
            'Int16' { "{0}i" -f [string]$value; break }
            'Int32' { "{0}i" -f [string]$value; break }
            'Int64' { "{0}i" -f [string]$value; break }
            'Decimal' { ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, '{0}', $value)); break }
            'Double' { ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, '{0}', $value)); break }
            'Single' { ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, '{0}', $value)); break }
            default { '"{0}"' -f (ConvertTo-EscapedFieldString -Value $value) }
        }

        "{0}={1}" -f (ConvertTo-EscapedTagValue -Value $key), $encodedValue
    }

    if (-not $fieldPairs) {
        throw 'Influx line requires at least one field.'
    }

    $measurementPart = ConvertTo-EscapedTagValue -Value $Measurement
    $tagsPart = if ($tagPairs) { ',' + ($tagPairs -join ',') } else { '' }
    $fieldsPart = $fieldPairs -join ','

    return "{0}{1} {2} {3}" -f $measurementPart, $tagsPart, $fieldsPart, $TimestampMs
}

function Get-CurlExecutable {
    $command = Get-Command -Name 'curl.exe' -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw 'curl.exe was not found in PATH.'
    }

    return $command.Source
}

function Get-ExpectedHttpCodeMatch {
    param(
        [int]$HttpCode,
        [int[]]$ExpectedHttpCodes
    )

    return $ExpectedHttpCodes -contains $HttpCode
}

function Get-ParsedValue {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Map,

        [Parameter(Mandatory = $true)]
        [string]$Key,

        [Parameter()]
        [string]$DefaultValue = ''
    )

    if ($Map.ContainsKey($Key) -and $null -ne $Map[$Key] -and -not [string]::IsNullOrWhiteSpace([string]$Map[$Key])) {
        return [string]$Map[$Key]
    }

    return $DefaultValue
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

function Get-InfluxToken {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$InfluxConfig,

        [Parameter(Mandatory = $true)]
        [string]$ConfigDirectory,

        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )

    $tokenValue = ''
    $protectedTokenFilePath = ''

    if ($InfluxConfig.PSObject.Properties.Name -contains 'credentialFilePath' -and -not [string]::IsNullOrWhiteSpace([string]$InfluxConfig.credentialFilePath)) {
        $protectedTokenFilePath = Get-FullPathFromBase -BasePath $ConfigDirectory -ChildPath ([string]$InfluxConfig.credentialFilePath)
        $tokenValue = Get-InfluxTokenFromProtectedFile -ProtectedTokenFilePath $protectedTokenFilePath
        if (-not [string]::IsNullOrWhiteSpace($tokenValue)) {
            Write-Log -Message ("Using InfluxDB token from protected token file '{0}'." -f $protectedTokenFilePath) -LogPath $LogPath
            return $tokenValue
        }

        Write-Log -Message ("Protected token file '{0}' was not found or did not return a token. Falling back to environment lookup." -f $protectedTokenFilePath) -Level 'WARN' -LogPath $LogPath
    }

    $tokenName = [string]$InfluxConfig.tokenEnvVar
    $tokenValue = [Environment]::GetEnvironmentVariable($tokenName, 'Process')
    if ([string]::IsNullOrWhiteSpace($tokenValue)) {
        $tokenValue = [Environment]::GetEnvironmentVariable($tokenName, 'User')
    }

    if (-not [string]::IsNullOrWhiteSpace($tokenValue)) {
        Write-Log -Message ("Using InfluxDB token from environment variable '{0}'." -f $tokenName) -Level 'WARN' -LogPath $LogPath
        return $tokenValue
    }

    throw "InfluxDB token was not found in the configured protected token file or environment variable '$tokenName'."
}

function Get-OptionalIntValue {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Source,

        [Parameter(Mandatory = $true)]
        [string]$PropertyName,

        [Parameter()]
        [int]$DefaultValue = 0
    )

    if ($Source.PSObject.Properties.Name -contains $PropertyName -and $null -ne $Source.$PropertyName) {
        return [int]$Source.$PropertyName
    }

    return $DefaultValue
}

function Invoke-CurlProbe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CurlPath,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun
    )

    $writeOut = @(
        'http_code=%{response_code}',
        'remote_ip=%{remote_ip}',
        'http_version=%{http_version}',
        'num_redirects=%{num_redirects}',
        'time_namelookup=%{time_namelookup}',
        'time_connect=%{time_connect}',
        'time_appconnect=%{time_appconnect}',
        'time_starttransfer=%{time_starttransfer}',
        'time_total=%{time_total}',
        'size_download=%{size_download}',
        'errormsg=%{errormsg}',
        'url_effective=%{url_effective}'
    ) -join "`n"

    $arguments = New-Object System.Collections.Generic.List[string]
    foreach ($value in @('-q', '--silent', '--show-error', '--no-progress-meter', '--globoff', '--output', 'nul')) {
        $arguments.Add([string]$value)
    }

    if ($ProbeRun.followRedirects) {
        $arguments.Add('--location')
        $arguments.Add('--max-redirs')
        $arguments.Add('5')
        $arguments.Add('--proto-redir')
        $arguments.Add('=http,https')
    }

    if (-not $ProbeRun.verifyTls) {
        $arguments.Add('--insecure')
    }

    foreach ($value in @(
        '--proto', '=http,https',
        '--connect-timeout', [string]$ProbeRun.connectTimeoutSeconds,
        '--max-time', [string]$ProbeRun.maxTimeSeconds,
        '--retry', [string]$ProbeRun.retryCount,
        '--retry-delay', [string]$ProbeRun.retryDelaySeconds,
        '--request', [string]$Target.method,
        '--user-agent', [string]$ProbeRun.userAgent,
        '--write-out', $writeOut,
        [string]$Target.url
    )) {
        $arguments.Add([string]$value)
    }

    $stdout = & $CurlPath @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $parsed = @{}

    foreach ($line in ($stdout -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        $separatorIndex = $line.IndexOf('=')
        if ($separatorIndex -gt 0) {
            $key = $line.Substring(0, $separatorIndex)
            $value = $line.Substring($separatorIndex + 1)
            $parsed[$key] = $value
        }
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        HttpCode = [int](Get-ParsedValue -Map $parsed -Key 'http_code' -DefaultValue '0')
        RemoteIp = Get-ParsedValue -Map $parsed -Key 'remote_ip' -DefaultValue ''
        HttpVersion = Get-ParsedValue -Map $parsed -Key 'http_version' -DefaultValue ''
        NumRedirects = [int](Get-ParsedValue -Map $parsed -Key 'num_redirects' -DefaultValue '0')
        TimeNameLookupMs = [math]::Round(([double](Get-ParsedValue -Map $parsed -Key 'time_namelookup' -DefaultValue '0')) * 1000, 2)
        TimeConnectMs = [math]::Round(([double](Get-ParsedValue -Map $parsed -Key 'time_connect' -DefaultValue '0')) * 1000, 2)
        TimeAppConnectMs = [math]::Round(([double](Get-ParsedValue -Map $parsed -Key 'time_appconnect' -DefaultValue '0')) * 1000, 2)
        TimeStartTransferMs = [math]::Round(([double](Get-ParsedValue -Map $parsed -Key 'time_starttransfer' -DefaultValue '0')) * 1000, 2)
        TimeTotalMs = [math]::Round(([double](Get-ParsedValue -Map $parsed -Key 'time_total' -DefaultValue '0')) * 1000, 2)
        SizeDownloadBytes = [double](Get-ParsedValue -Map $parsed -Key 'size_download' -DefaultValue '0')
        ErrorMessage = Get-ParsedValue -Map $parsed -Key 'errormsg' -DefaultValue ''
        EffectiveUrl = Get-ParsedValue -Map $parsed -Key 'url_effective' -DefaultValue ([string]$Target.url)
        IsExpectedHttpCode = Get-ExpectedHttpCodeMatch -HttpCode ([int](Get-ParsedValue -Map $parsed -Key 'http_code' -DefaultValue '0')) -ExpectedHttpCodes ([int[]]$Target.expectedHttpCodes)
    }
}

$scriptStart = Get-Date
$scriptBasePath = Get-ScriptBasePath
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\config\probe-catalog.json'
}

$resolvedConfigPath = Resolve-Path -Path $ConfigPath
$config = Get-Content -Path $resolvedConfigPath -Raw | ConvertFrom-Json
$configDirectory = Split-Path -Path $resolvedConfigPath -Parent
$resolvedRunReportPath = ''
if (-not [string]::IsNullOrWhiteSpace($RunReportPath)) {
    $resolvedRunReportPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath $RunReportPath
}

$logDirectory = Join-Path -Path (Split-Path -Path $resolvedConfigPath -Parent) -ChildPath "..\$($config.probeRun.logDirectory)"
$logDirectory = [System.IO.Path]::GetFullPath($logDirectory)
if (-not (Test-Path -Path $logDirectory)) {
    New-Item -Path $logDirectory -ItemType Directory -Force | Out-Null
}

$runDate = Get-Date
$logPath = Join-Path -Path $logDirectory -ChildPath ("qoe-probe-{0}.log" -f $runDate.ToString('yyyy-MM-dd'))
$curlPath = Get-CurlExecutable
$lines = New-Object System.Collections.Generic.List[string]
$successCount = 0
$failureCount = 0
$tokenValue = ''
$enabledTargets = @($config.targets | Where-Object { $_.enabled })
$startJitterSecondsMax = Get-OptionalIntValue -Source $config.probeRun -PropertyName 'startJitterSecondsMax' -DefaultValue 0
$targetDelayMilliseconds = Get-OptionalIntValue -Source $config.probeRun -PropertyName 'targetDelayMilliseconds' -DefaultValue 0
$influxWriteTimeoutSeconds = Get-OptionalIntValue -Source $config.influx -PropertyName 'writeTimeoutSeconds' -DefaultValue 30
$runJitterSeconds = 0
$targetReports = New-Object System.Collections.Generic.List[object]
$writeAttempted = $false
$writeSucceeded = $false
$writeUri = ''
$fatalErrorMessage = ''
$threw = $false

try {
    Write-Log -Message "Starting QoE probe using config $resolvedConfigPath" -LogPath $logPath

    if ($startJitterSecondsMax -gt 0) {
        $runJitterSeconds = Get-Random -Minimum 0 -Maximum ($startJitterSecondsMax + 1)
        if ($runJitterSeconds -gt 0) {
            Write-Log -Message ("Applying start jitter of {0} second(s) to reduce fixed-schedule burst patterns." -f $runJitterSeconds) -LogPath $logPath
            Start-Sleep -Seconds $runJitterSeconds
        }
    }

    if (-not $SkipInfluxWrite) {
        $writeAttempted = $true
        $tokenValue = Get-InfluxToken -InfluxConfig $config.influx -ConfigDirectory $configDirectory -LogPath $logPath
    }

    for ($targetIndex = 0; $targetIndex -lt $enabledTargets.Count; $targetIndex++) {
        $target = $enabledTargets[$targetIndex]
        $targetStart = Get-Date
        try {
            $result = Invoke-CurlProbe -CurlPath $curlPath -Target $target -ProbeRun $config.probeRun
            $available = ($result.ExitCode -eq 0 -and $result.IsExpectedHttpCode)
            if ($available) {
                $successCount++
            }
            else {
                $failureCount++
            }

            $errorClass = if ($result.ExitCode -eq 0 -and -not $result.IsExpectedHttpCode) {
                'unexpected_http_status'
            }
            elseif ($result.ExitCode -eq 6) {
                'dns_resolution'
            }
            elseif ($result.ExitCode -eq 7) {
                'connect'
            }
            elseif ($result.ExitCode -eq 22) {
                'http_error'
            }
            elseif ($result.ExitCode -eq 28) {
                'timeout'
            }
            elseif ($result.ExitCode -eq 35 -or $result.ExitCode -eq 60) {
                'tls'
            }
            elseif ($result.ExitCode -eq 0) {
                ''
            }
            else {
                'curl_error'
            }

            $tags = @{
                probe_id = $config.probe.probeId
                probe_type = $config.probe.probeType
                site = $config.probe.site
                environment = $config.probe.environment
                service = $target.service
                endpoint_name = $target.endpointName
                probe_version = $config.probe.probeVersion
            }

            $fields = @{
                available = [bool]$available
                http_status = [int]$result.HttpCode
                curl_exit_code = [int]$result.ExitCode
                time_namelookup_ms = [double]$result.TimeNameLookupMs
                time_connect_ms = [double]$result.TimeConnectMs
                time_appconnect_ms = [double]$result.TimeAppConnectMs
                time_starttransfer_ms = [double]$result.TimeStartTransferMs
                time_total_ms = [double]$result.TimeTotalMs
                size_download_bytes = [double]$result.SizeDownloadBytes
                num_redirects = [int]$result.NumRedirects
                http_version = [string]$result.HttpVersion
                remote_ip = [string]$result.RemoteIp
                error_class = [string]$errorClass
                error_detail = [string]$result.ErrorMessage
                effective_url = [string]$result.EffectiveUrl
                run_duration_ms = [double]((Get-Date) - $targetStart).TotalMilliseconds
            }

            $timestampMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
            $lines.Add((Get-InfluxLine -Measurement $config.probeRun.measurement -Tags $tags -Fields $fields -TimestampMs $timestampMs))

            $targetReports.Add([pscustomobject]@{
                service = [string]$target.service
                endpoint_name = [string]$target.endpointName
                url = [string]$target.url
                available = [bool]$available
                http_status = [int]$result.HttpCode
                curl_exit_code = [int]$result.ExitCode
                time_namelookup_ms = [double]$result.TimeNameLookupMs
                time_connect_ms = [double]$result.TimeConnectMs
                time_appconnect_ms = [double]$result.TimeAppConnectMs
                time_starttransfer_ms = [double]$result.TimeStartTransferMs
                time_total_ms = [double]$result.TimeTotalMs
                size_download_bytes = [double]$result.SizeDownloadBytes
                num_redirects = [int]$result.NumRedirects
                http_version = [string]$result.HttpVersion
                remote_ip = [string]$result.RemoteIp
                error_class = [string]$errorClass
                error_detail = [string]$result.ErrorMessage
                effective_url = [string]$result.EffectiveUrl
                run_duration_ms = [double]$fields.run_duration_ms
            }) | Out-Null

            Write-Log -Message ("Target {0}/{1} completed with HTTP {2}, curl exit {3}, total {4} ms" -f $target.service, $target.endpointName, $result.HttpCode, $result.ExitCode, $result.TimeTotalMs) -LogPath $logPath
        }
        catch {
            $failureCount++
            Write-Log -Message ("Target {0}/{1} failed: {2}" -f $target.service, $target.endpointName, $_.Exception.Message) -Level 'ERROR' -LogPath $logPath

            $tags = @{
                probe_id = $config.probe.probeId
                probe_type = $config.probe.probeType
                site = $config.probe.site
                environment = $config.probe.environment
                service = $target.service
                endpoint_name = $target.endpointName
                probe_version = $config.probe.probeVersion
            }

            $fields = @{
                available = $false
                http_status = 0
                curl_exit_code = -1
                time_namelookup_ms = 0.0
                time_connect_ms = 0.0
                time_appconnect_ms = 0.0
                time_starttransfer_ms = 0.0
                time_total_ms = 0.0
                size_download_bytes = 0.0
                num_redirects = 0
                http_version = ''
                remote_ip = ''
                error_class = 'probe_exception'
                error_detail = [string]$_.Exception.Message
                effective_url = [string]$target.url
                run_duration_ms = [double]((Get-Date) - $targetStart).TotalMilliseconds
            }

            $timestampMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
            $lines.Add((Get-InfluxLine -Measurement $config.probeRun.measurement -Tags $tags -Fields $fields -TimestampMs $timestampMs))

            $targetReports.Add([pscustomobject]@{
                service = [string]$target.service
                endpoint_name = [string]$target.endpointName
                url = [string]$target.url
                available = $false
                http_status = 0
                curl_exit_code = -1
                time_namelookup_ms = 0.0
                time_connect_ms = 0.0
                time_appconnect_ms = 0.0
                time_starttransfer_ms = 0.0
                time_total_ms = 0.0
                size_download_bytes = 0.0
                num_redirects = 0
                http_version = ''
                remote_ip = ''
                error_class = 'probe_exception'
                error_detail = [string]$_.Exception.Message
                effective_url = [string]$target.url
                run_duration_ms = [double]$fields.run_duration_ms
            }) | Out-Null
        }

        if ($targetDelayMilliseconds -gt 0 -and $targetIndex -lt ($enabledTargets.Count - 1)) {
            Start-Sleep -Milliseconds $targetDelayMilliseconds
        }
    }

    $probeFields = @{
        success_count = [int]$successCount
        failure_count = [int]$failureCount
        run_duration_ms = [double]((Get-Date) - $scriptStart).TotalMilliseconds
        write_attempted = [bool]$writeAttempted
        write_succeeded = $false
        target_count = [int]$enabledTargets.Count
    }

    if (-not $SkipInfluxWrite) {
        $writeUri = "{0}/api/v2/write?org={1}&bucket={2}&precision={3}" -f $config.influx.baseUrl.TrimEnd('/'), [System.Uri]::EscapeDataString([string]$config.influx.org), [System.Uri]::EscapeDataString([string]$config.influx.bucket), [System.Uri]::EscapeDataString([string]$config.influx.precision)
        $payload = ($lines -join "`n")

        Invoke-RestMethod -Uri $writeUri -Method Post -Headers @{ Authorization = "Token $tokenValue" } -Body $payload -ContentType 'text/plain; charset=utf-8' -TimeoutSec $influxWriteTimeoutSeconds | Out-Null
        $probeFields.write_succeeded = $true
        $writeSucceeded = $true
        Write-Log -Message ("Wrote {0} measurement lines to InfluxDB." -f $lines.Count) -LogPath $logPath
    }
    else {
        Write-Log -Message 'SkipInfluxWrite flag set. Metrics were not sent to InfluxDB.' -Level 'WARN' -LogPath $logPath
    }

    $probeTags = @{
        probe_id = $config.probe.probeId
        probe_type = $config.probe.probeType
        site = $config.probe.site
        environment = $config.probe.environment
        probe_version = $config.probe.probeVersion
    }

    $probeTimestampMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $lines.Add((Get-InfluxLine -Measurement $config.probeRun.probeMeasurement -Tags $probeTags -Fields $probeFields -TimestampMs $probeTimestampMs))

    if (-not $SkipInfluxWrite -and $probeFields.write_succeeded) {
        $writeUri = "{0}/api/v2/write?org={1}&bucket={2}&precision={3}" -f $config.influx.baseUrl.TrimEnd('/'), [System.Uri]::EscapeDataString([string]$config.influx.org), [System.Uri]::EscapeDataString([string]$config.influx.bucket), [System.Uri]::EscapeDataString([string]$config.influx.precision)
        $probeOnlyPayload = $lines[-1]
        Invoke-RestMethod -Uri $writeUri -Method Post -Headers @{ Authorization = "Token $tokenValue" } -Body $probeOnlyPayload -ContentType 'text/plain; charset=utf-8' -TimeoutSec $influxWriteTimeoutSeconds | Out-Null
    }

    Write-Log -Message ("QoE probe finished. Success={0}, Failure={1}, Duration={2} ms" -f $successCount, $failureCount, [math]::Round(((Get-Date) - $scriptStart).TotalMilliseconds, 2)) -LogPath $logPath
}
catch {
    $threw = $true
    $fatalErrorMessage = [string]$_.Exception.Message
    Write-Log -Message $_.Exception.Message -Level 'ERROR' -LogPath $logPath
    throw
}
finally {
    if (-not [string]::IsNullOrWhiteSpace($resolvedRunReportPath)) {
        $reportCompletedAt = Get-Date
        $report = [pscustomobject]@{
            started_at_utc = $scriptStart.ToUniversalTime().ToString('o')
            completed_at_utc = $reportCompletedAt.ToUniversalTime().ToString('o')
            config_path = [string]$resolvedConfigPath
            log_path = [string]$logPath
            probe_id = [string]$config.probe.probeId
            probe_type = [string]$config.probe.probeType
            site = [string]$config.probe.site
            environment = [string]$config.probe.environment
            measurement = [string]$config.probeRun.measurement
            probe_measurement = [string]$config.probeRun.probeMeasurement
            skip_influx_write = [bool]$SkipInfluxWrite
            write_attempted = [bool]$writeAttempted
            write_succeeded = [bool]$writeSucceeded
            write_uri = [string]$writeUri
            success_count = [int]$successCount
            failure_count = [int]$failureCount
            target_count = [int]$enabledTargets.Count
            run_duration_ms = [double]((Get-Date) - $scriptStart).TotalMilliseconds
            start_jitter_seconds = [int]$runJitterSeconds
            target_delay_milliseconds = [int]$targetDelayMilliseconds
            threw = [bool]$threw
            fatal_error = [string]$fatalErrorMessage
            targets = @($targetReports)
        }

        Write-RunReport -Path $resolvedRunReportPath -Report $report
        Write-Log -Message ("Structured run report written to {0}" -f $resolvedRunReportPath) -LogPath $logPath
    }
}