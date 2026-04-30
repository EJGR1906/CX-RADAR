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

function Get-OptionalStringValue {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Source,

        [Parameter(Mandatory = $true)]
        [string]$PropertyName,

        [Parameter()]
        [string]$DefaultValue = ''
    )

    if ($Source.PSObject.Properties.Name -contains $PropertyName -and $null -ne $Source.$PropertyName -and -not [string]::IsNullOrWhiteSpace([string]$Source.$PropertyName)) {
        return [string]$Source.$PropertyName
    }

    return $DefaultValue
}

function Resolve-SpeedTestCommandPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    $expandedCommandName = [Environment]::ExpandEnvironmentVariables($CommandName)

    if ([System.IO.Path]::IsPathRooted($expandedCommandName)) {
        if (-not (Test-Path -Path $expandedCommandName -PathType Leaf)) {
            throw "Speed-test CLI was not found at '$expandedCommandName'."
        }

        return [System.IO.Path]::GetFullPath($expandedCommandName)
    }

    $command = Get-Command -Name $expandedCommandName -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Speed-test CLI '$expandedCommandName' was not found in PATH."
    }

    return $command.Source
}

function ConvertTo-CommandLineArgumentString {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    return ($Arguments | ForEach-Object {
        if ($_ -match '[\s"]') {
            '"{0}"' -f ($_.Replace('"', '\"'))
        }
        else {
            $_
        }
    }) -join ' '
}

function Invoke-SpeedTestCli {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandPath,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$RunConfig,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target
    )

    $provider = Get-OptionalStringValue -Source $Target -PropertyName 'provider'
    if ($provider -ne 'ookla') {
        throw "Unsupported speed-test provider '$provider'. This implementation currently supports only 'ookla'."
    }

    $arguments = New-Object System.Collections.Generic.List[string]
    if ($RunConfig.acceptLicense) {
        $arguments.Add('--accept-license')
    }
    if ($RunConfig.acceptGdpr) {
        $arguments.Add('--accept-gdpr')
    }

    $outputFormat = Get-OptionalStringValue -Source $RunConfig -PropertyName 'outputFormat' -DefaultValue 'json'
    if (-not [string]::IsNullOrWhiteSpace($outputFormat)) {
        $arguments.Add("--format=$outputFormat")
    }

    if ($Target.PSObject.Properties.Name -contains 'serverId' -and -not [string]::IsNullOrWhiteSpace([string]$Target.serverId)) {
        $arguments.Add('--server-id')
        $arguments.Add([string]$Target.serverId)
    }

    if ($RunConfig.PSObject.Properties.Name -contains 'extraArguments' -and $null -ne $RunConfig.extraArguments) {
        foreach ($argument in @($RunConfig.extraArguments)) {
            if (-not [string]::IsNullOrWhiteSpace([string]$argument)) {
                $arguments.Add([string]$argument)
            }
        }
    }

    $processStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processStartInfo.FileName = $CommandPath
    $processStartInfo.Arguments = ConvertTo-CommandLineArgumentString -Arguments @($arguments)
    $processStartInfo.UseShellExecute = $false
    $processStartInfo.RedirectStandardOutput = $true
    $processStartInfo.RedirectStandardError = $true
    $processStartInfo.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $processStartInfo

    $timeoutSeconds = Get-OptionalIntValue -Source $RunConfig -PropertyName 'timeoutSeconds' -DefaultValue 120
    $processStart = Get-Date
    $null = $process.Start()
    $timedOut = -not $process.WaitForExit($timeoutSeconds * 1000)
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

    $stdout = $process.StandardOutput.ReadToEnd().Trim()
    $stderr = $process.StandardError.ReadToEnd().Trim()
    $exitCode = if ($timedOut) { -1 } else { [int]$process.ExitCode }

    return [pscustomobject]@{
        Arguments = @($arguments)
        TimedOut = [bool]$timedOut
        ExitCode = [int]$exitCode
        StdOut = [string]$stdout
        StdErr = [string]$stderr
        DurationMs = [double][math]::Round(((Get-Date) - $processStart).TotalMilliseconds, 2)
    }
}

function Get-JsonPayloadFromText {
    param(
        [Parameter()]
        [string]$Text
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ''
    }

    $trimmed = $Text.Trim()
    if ($trimmed.StartsWith('{') -or $trimmed.StartsWith('[')) {
        return $trimmed
    }

    $firstBrace = $trimmed.IndexOf('{')
    $lastBrace = $trimmed.LastIndexOf('}')
    if ($firstBrace -ge 0 -and $lastBrace -gt $firstBrace) {
        return $trimmed.Substring($firstBrace, $lastBrace - $firstBrace + 1)
    }

    return ''
}

function Get-NestedPropertyValue {
    param(
        [Parameter()]
        [object]$Object,

        [Parameter(Mandatory = $true)]
        [string[]]$Path
    )

    $current = $Object
    foreach ($segment in $Path) {
        if ($null -eq $current) {
            return $null
        }

        if ($current -isnot [psobject]) {
            return $null
        }

        $property = $current.PSObject.Properties[$segment]
        if ($null -eq $property) {
            return $null
        }

        $current = $property.Value
    }

    return $current
}

function ConvertTo-DoubleOrDefault {
    param(
        [Parameter()]
        [object]$Value,

        [Parameter()]
        [double]$DefaultValue = 0.0
    )

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return $DefaultValue
    }

    try {
        return [double]$Value
    }
    catch {
        return $DefaultValue
    }
}

function ConvertTo-StringOrDefault {
    param(
        [Parameter()]
        [object]$Value,

        [Parameter()]
        [string]$DefaultValue = ''
    )

    if ($null -eq $Value) {
        return $DefaultValue
    }

    $stringValue = [string]$Value
    if ([string]::IsNullOrWhiteSpace($stringValue)) {
        return $DefaultValue
    }

    return $stringValue
}

function Get-SpeedTestResult {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProcessResult,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target
    )

    $errorClass = ''
    $errorDetail = ''
    $parsed = $null

    if ($ProcessResult.TimedOut) {
        $errorClass = 'timeout'
        $errorDetail = 'Speed-test CLI timed out.'
    }
    else {
        $jsonCandidate = if (-not [string]::IsNullOrWhiteSpace($ProcessResult.StdOut)) {
            Get-JsonPayloadFromText -Text $ProcessResult.StdOut
        }
        else {
            Get-JsonPayloadFromText -Text $ProcessResult.StdErr
        }

        if (-not [string]::IsNullOrWhiteSpace($jsonCandidate)) {
            try {
                $parsed = $jsonCandidate | ConvertFrom-Json -ErrorAction Stop
            }
            catch {
                $errorClass = 'parse_error'
                $errorDetail = [string]$_.Exception.Message
            }
        }
        elseif ($ProcessResult.ExitCode -ne 0) {
            $errorClass = 'cli_error'
            $errorDetail = if (-not [string]::IsNullOrWhiteSpace($ProcessResult.StdErr)) { $ProcessResult.StdErr } else { $ProcessResult.StdOut }
        }
    }

    $resultType = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('type'))
    if ([string]::IsNullOrWhiteSpace($errorClass) -and $ProcessResult.ExitCode -eq 0 -and $resultType -ne 'result') {
        $errorClass = 'unexpected_result'
        $errorDetail = if ([string]::IsNullOrWhiteSpace($resultType)) { 'Speed-test CLI did not return result.type.' } else { "Unexpected result.type '$resultType'." }
    }

    $downloadBandwidthBytesPerSecond = ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('download', 'bandwidth'))
    $uploadBandwidthBytesPerSecond = ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('upload', 'bandwidth'))
    $downloadMbps = [math]::Round(($downloadBandwidthBytesPerSecond * 8.0) / 1000000.0, 2)
    $uploadMbps = [math]::Round(($uploadBandwidthBytesPerSecond * 8.0) / 1000000.0, 2)

    return [pscustomobject]@{
        ExitCode = [int]$ProcessResult.ExitCode
        TimedOut = [bool]$ProcessResult.TimedOut
        Provider = ConvertTo-StringOrDefault -Value $Target.provider -DefaultValue 'ookla'
        ResultType = $resultType
        LatencyMs = [math]::Round((ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('ping', 'latency'))), 2)
        JitterMs = [math]::Round((ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('ping', 'jitter'))), 2)
        PacketLossPct = [math]::Round((ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('packetLoss'))), 2)
        DownloadBandwidthBytesPerSecond = [double]$downloadBandwidthBytesPerSecond
        DownloadMbps = [double]$downloadMbps
        DownloadBytes = [double](ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('download', 'bytes')))
        DownloadElapsedMs = [double](ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('download', 'elapsed')))
        UploadBandwidthBytesPerSecond = [double]$uploadBandwidthBytesPerSecond
        UploadMbps = [double]$uploadMbps
        UploadBytes = [double](ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('upload', 'bytes')))
        UploadElapsedMs = [double](ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('upload', 'elapsed')))
        ServerId = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('server', 'id'))
        ServerName = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('server', 'name'))
        ServerLocation = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('server', 'location'))
        ServerCountry = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('server', 'country'))
        ServerHost = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('server', 'host'))
        ServerIp = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('server', 'ip'))
        InterfaceExternalIp = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('interface', 'externalIp'))
        InterfaceInternalIp = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('interface', 'internalIp'))
        Isp = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('isp'))
        ResultId = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('result', 'id'))
        ResultUrl = ConvertTo-StringOrDefault -Value (Get-NestedPropertyValue -Object $parsed -Path @('result', 'url'))
        ErrorClass = $errorClass
        ErrorDetail = if (-not [string]::IsNullOrWhiteSpace($errorDetail)) { $errorDetail } elseif (-not [string]::IsNullOrWhiteSpace($ProcessResult.StdErr)) { $ProcessResult.StdErr } else { '' }
        RawStdOut = [string]$ProcessResult.StdOut
        RawStdErr = [string]$ProcessResult.StdErr
        RunDurationMs = [double]$ProcessResult.DurationMs
        Available = [bool]([string]::IsNullOrWhiteSpace($errorClass) -and $ProcessResult.ExitCode -eq 0)
    }
}

$scriptStart = Get-Date
$scriptBasePath = Get-ScriptBasePath
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\config\speed-test-catalog.json'
}

$resolvedConfigPath = Resolve-Path -Path $ConfigPath
$config = Get-Content -Path $resolvedConfigPath -Raw | ConvertFrom-Json
$configDirectory = Split-Path -Path $resolvedConfigPath -Parent
$resolvedRunReportPath = ''
if (-not [string]::IsNullOrWhiteSpace($RunReportPath)) {
    $resolvedRunReportPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath $RunReportPath
}

$logDirectory = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath ("..\{0}" -f $config.speedTestRun.logDirectory)
if (-not (Test-Path -Path $logDirectory -PathType Container)) {
    New-Item -Path $logDirectory -ItemType Directory -Force | Out-Null
}

$runDate = Get-Date
$logPath = Join-Path -Path $logDirectory -ChildPath ("qoe-speed-test-{0}.log" -f $runDate.ToString('yyyy-MM-dd'))
$commandPath = Resolve-SpeedTestCommandPath -CommandName ([string]$config.speedTestRun.cliCommand)
$lines = New-Object System.Collections.Generic.List[string]
$successCount = 0
$failureCount = 0
$tokenValue = ''
$enabledTargets = @($config.targets | Where-Object { $_.enabled })
$startJitterSecondsMax = Get-OptionalIntValue -Source $config.speedTestRun -PropertyName 'startJitterSecondsMax' -DefaultValue 0
$targetDelayMilliseconds = Get-OptionalIntValue -Source $config.speedTestRun -PropertyName 'targetDelayMilliseconds' -DefaultValue 0
$influxWriteTimeoutSeconds = Get-OptionalIntValue -Source $config.influx -PropertyName 'writeTimeoutSeconds' -DefaultValue 30
$runJitterSeconds = 0
$targetReports = New-Object System.Collections.Generic.List[object]
$writeAttempted = $false
$writeSucceeded = $false
$writeUri = ''
$fatalErrorMessage = ''
$threw = $false

try {
    Write-Log -Message "Starting QoE speed test using config $resolvedConfigPath" -LogPath $logPath

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
            $processResult = Invoke-SpeedTestCli -CommandPath $commandPath -RunConfig $config.speedTestRun -Target $target
            $result = Get-SpeedTestResult -ProcessResult $processResult -Target $target

            if ($result.Available) {
                $successCount++
            }
            else {
                $failureCount++
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
                available = [bool]$result.Available
                cli_exit_code = [int]$result.ExitCode
                latency_ms = [double]$result.LatencyMs
                jitter_ms = [double]$result.JitterMs
                packet_loss_pct = [double]$result.PacketLossPct
                download_bandwidth_bytes_per_s = [double]$result.DownloadBandwidthBytesPerSecond
                download_mbps = [double]$result.DownloadMbps
                download_bytes = [double]$result.DownloadBytes
                download_elapsed_ms = [double]$result.DownloadElapsedMs
                upload_bandwidth_bytes_per_s = [double]$result.UploadBandwidthBytesPerSecond
                upload_mbps = [double]$result.UploadMbps
                upload_bytes = [double]$result.UploadBytes
                upload_elapsed_ms = [double]$result.UploadElapsedMs
                provider = [string]$result.Provider
                server_id = [string]$result.ServerId
                server_name = [string]$result.ServerName
                server_location = [string]$result.ServerLocation
                server_country = [string]$result.ServerCountry
                server_host = [string]$result.ServerHost
                server_ip = [string]$result.ServerIp
                interface_external_ip = [string]$result.InterfaceExternalIp
                interface_internal_ip = [string]$result.InterfaceInternalIp
                isp = [string]$result.Isp
                result_id = [string]$result.ResultId
                result_url = [string]$result.ResultUrl
                error_class = [string]$result.ErrorClass
                error_detail = [string]$result.ErrorDetail
                run_duration_ms = [double]((Get-Date) - $targetStart).TotalMilliseconds
            }

            $timestampMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
            $lines.Add((Get-InfluxLine -Measurement $config.speedTestRun.measurement -Tags $tags -Fields $fields -TimestampMs $timestampMs))

            $targetReports.Add([pscustomobject]@{
                service = [string]$target.service
                endpoint_name = [string]$target.endpointName
                provider = [string]$result.Provider
                available = [bool]$result.Available
                cli_exit_code = [int]$result.ExitCode
                latency_ms = [double]$result.LatencyMs
                jitter_ms = [double]$result.JitterMs
                packet_loss_pct = [double]$result.PacketLossPct
                download_mbps = [double]$result.DownloadMbps
                upload_mbps = [double]$result.UploadMbps
                server_id = [string]$result.ServerId
                server_name = [string]$result.ServerName
                server_location = [string]$result.ServerLocation
                server_country = [string]$result.ServerCountry
                result_url = [string]$result.ResultUrl
                error_class = [string]$result.ErrorClass
                error_detail = [string]$result.ErrorDetail
                run_duration_ms = [double]$fields.run_duration_ms
            }) | Out-Null

            Write-Log -Message ("Target {0}/{1} completed with download {2} Mbps, upload {3} Mbps, latency {4} ms, exit {5}" -f $target.service, $target.endpointName, $result.DownloadMbps, $result.UploadMbps, $result.LatencyMs, $result.ExitCode) -LogPath $logPath
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
                cli_exit_code = -1
                latency_ms = 0.0
                jitter_ms = 0.0
                packet_loss_pct = 0.0
                download_bandwidth_bytes_per_s = 0.0
                download_mbps = 0.0
                download_bytes = 0.0
                download_elapsed_ms = 0.0
                upload_bandwidth_bytes_per_s = 0.0
                upload_mbps = 0.0
                upload_bytes = 0.0
                upload_elapsed_ms = 0.0
                provider = [string](Get-OptionalStringValue -Source $target -PropertyName 'provider' -DefaultValue '')
                server_id = ''
                server_name = ''
                server_location = ''
                server_country = ''
                server_host = ''
                server_ip = ''
                interface_external_ip = ''
                interface_internal_ip = ''
                isp = ''
                result_id = ''
                result_url = ''
                error_class = 'probe_exception'
                error_detail = [string]$_.Exception.Message
                run_duration_ms = [double]((Get-Date) - $targetStart).TotalMilliseconds
            }

            $timestampMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
            $lines.Add((Get-InfluxLine -Measurement $config.speedTestRun.measurement -Tags $tags -Fields $fields -TimestampMs $timestampMs))

            $targetReports.Add([pscustomobject]@{
                service = [string]$target.service
                endpoint_name = [string]$target.endpointName
                provider = [string]$fields.provider
                available = $false
                cli_exit_code = -1
                latency_ms = 0.0
                jitter_ms = 0.0
                packet_loss_pct = 0.0
                download_mbps = 0.0
                upload_mbps = 0.0
                server_id = ''
                server_name = ''
                server_location = ''
                server_country = ''
                result_url = ''
                error_class = 'probe_exception'
                error_detail = [string]$_.Exception.Message
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
    $lines.Add((Get-InfluxLine -Measurement $config.speedTestRun.probeMeasurement -Tags $probeTags -Fields $probeFields -TimestampMs $probeTimestampMs))

    if (-not $SkipInfluxWrite -and $probeFields.write_succeeded) {
        $writeUri = "{0}/api/v2/write?org={1}&bucket={2}&precision={3}" -f $config.influx.baseUrl.TrimEnd('/'), [System.Uri]::EscapeDataString([string]$config.influx.org), [System.Uri]::EscapeDataString([string]$config.influx.bucket), [System.Uri]::EscapeDataString([string]$config.influx.precision)
        $probeOnlyPayload = $lines[-1]
        Invoke-RestMethod -Uri $writeUri -Method Post -Headers @{ Authorization = "Token $tokenValue" } -Body $probeOnlyPayload -ContentType 'text/plain; charset=utf-8' -TimeoutSec $influxWriteTimeoutSeconds | Out-Null
    }

    Write-Log -Message ("QoE speed test finished. Success={0}, Failure={1}, Duration={2} ms" -f $successCount, $failureCount, [math]::Round(((Get-Date) - $scriptStart).TotalMilliseconds, 2)) -LogPath $logPath
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
            measurement = [string]$config.speedTestRun.measurement
            probe_measurement = [string]$config.speedTestRun.probeMeasurement
            skip_influx_write = [bool]$SkipInfluxWrite
            cli_command = [string]$config.speedTestRun.cliCommand
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