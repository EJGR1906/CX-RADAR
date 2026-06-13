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
    param(
        [Parameter()]
        [string]$ScriptBasePath = ''
    )

    if (-not [string]::IsNullOrWhiteSpace($ScriptBasePath)) {
        $repoRoot = Get-FullPathFromBase -BasePath $ScriptBasePath -ChildPath '..'
        $portableCurlPath = Join-Path -Path $repoRoot -ChildPath 'bin\curl.exe'
        if (Test-Path -Path $portableCurlPath -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($portableCurlPath)
        }
    }

    $systemCurlPath = Join-Path -Path $env:SystemRoot -ChildPath 'System32\curl.exe'
    if (Test-Path -Path $systemCurlPath -PathType Leaf) {
        return [System.IO.Path]::GetFullPath($systemCurlPath)
    }

    $command = Get-Command -Name 'curl.exe' -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw 'curl.exe was not found in the project bin directory or Windows System32.'
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

function Invoke-ExternalProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandPath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter()]
        [int]$TimeoutSeconds = 120,

        [Parameter()]
        [hashtable]$EnvironmentVariables = @{},

        [Parameter()]
        [string]$WorkingDirectory = ''
    )

    if (-not (Test-Path -Path $CommandPath -PathType Leaf)) {
        throw "Command '$CommandPath' was not found."
    }

    $processStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processStartInfo.FileName = $CommandPath
    $processStartInfo.Arguments = ConvertTo-CommandLineArgumentString -Arguments $Arguments
    $processStartInfo.UseShellExecute = $false
    $processStartInfo.RedirectStandardOutput = $true
    $processStartInfo.RedirectStandardError = $true
    $processStartInfo.CreateNoWindow = $true

    if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
        $processStartInfo.WorkingDirectory = $WorkingDirectory
    }
    else {
        $processStartInfo.WorkingDirectory = Split-Path -Path $CommandPath -Parent
    }

    foreach ($environmentKey in $EnvironmentVariables.Keys) {
        $processStartInfo.EnvironmentVariables[$environmentKey] = [string]$EnvironmentVariables[$environmentKey]
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $processStartInfo

    $processStart = Get-Date
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

    $stdout = $process.StandardOutput.ReadToEnd().Trim()
    $stderr = $process.StandardError.ReadToEnd().Trim()
    $exitCode = if ($timedOut) { -1 } else { [int]$process.ExitCode }

    return [pscustomobject]@{
        Arguments = @($Arguments)
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

    $trimmedText = $Text.Trim()
    if ($trimmedText.StartsWith('{') -or $trimmedText.StartsWith('[')) {
        return $trimmedText
    }

    $firstBraceIndex = $trimmedText.IndexOf('{')
    $lastBraceIndex = $trimmedText.LastIndexOf('}')
    if ($firstBraceIndex -ge 0 -and $lastBraceIndex -gt $firstBraceIndex) {
        return $trimmedText.Substring($firstBraceIndex, $lastBraceIndex - $firstBraceIndex + 1)
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

    $currentValue = $Object
    foreach ($segment in $Path) {
        if ($null -eq $currentValue) {
            return $null
        }

        if ($currentValue -isnot [psobject]) {
            return $null
        }

        $property = $currentValue.PSObject.Properties[$segment]
        if ($null -eq $property) {
            return $null
        }

        $currentValue = $property.Value
    }

    return $currentValue
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

function Get-PortableTools {
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
        BinRoot = Get-FullPathFromBase -BasePath $repoRoot -ChildPath 'bin'
        NodeExe = Get-FullPathFromBase -BasePath $repoRoot -ChildPath (Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'nodeExe' -DefaultValue 'bin\node\node.exe')
        FastCliScript = Get-FullPathFromBase -BasePath $repoRoot -ChildPath (Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'fastCliScript' -DefaultValue 'bin\fast-cli\node_modules\fast-cli\distribution\cli.js')
        YtDlpExe = Get-FullPathFromBase -BasePath $repoRoot -ChildPath (Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'ytDlpExe' -DefaultValue 'bin\yt-dlp.exe')
        PuppeteerCacheDir = Get-FullPathFromBase -BasePath $repoRoot -ChildPath (Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'puppeteerCacheDir' -DefaultValue 'bin\puppeteer-cache')
        TemporaryDirectory = Get-FullPathFromBase -BasePath $repoRoot -ChildPath (Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'temporaryDirectory' -DefaultValue 'bin\tmp')
        NetworkQualityExe = Get-PortableToolProperty -PortableToolsConfig $portableToolsConfig -PropertyName 'networkQualityExe' -DefaultValue $networkQualityDefaultPath
    }
}

function Get-SafeFileNameToken {
    param(
        [Parameter()]
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return 'target'
    }

    $sanitizedValue = $Value
    foreach ($invalidCharacter in [System.IO.Path]::GetInvalidFileNameChars()) {
        $sanitizedValue = $sanitizedValue.Replace([string]$invalidCharacter, '_')
    }

    if ([string]::IsNullOrWhiteSpace($sanitizedValue)) {
        return 'target'
    }

    return $sanitizedValue
}

function Ensure-DirectoryExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -Path $Path -PathType Container)) {
        New-Item -Path $Path -ItemType Directory -Force | Out-Null
    }
}

function Remove-PathIfExists {
    param(
        [Parameter()]
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    try {
        if (Test-Path -Path $Path) {
            Remove-Item -Path $Path -Recurse -Force
        }
    }
    catch {
    }
}

function New-MeasurementTemporaryDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools,

        [Parameter(Mandatory = $true)]
        [string]$Prefix,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target
    )

    Ensure-DirectoryExists -Path $PortableTools.TemporaryDirectory

    $targetToken = '{0}-{1}' -f (Get-SafeFileNameToken -Value ([string]$Target.service)), (Get-SafeFileNameToken -Value ([string]$Target.endpointName))
    $runToken = [System.Guid]::NewGuid().ToString('N')
    $temporaryPath = Join-Path -Path $PortableTools.TemporaryDirectory -ChildPath ('{0}-{1}-{2}' -f $Prefix, $targetToken, $runToken)

    Ensure-DirectoryExists -Path $temporaryPath
    return $temporaryPath
}

<#
.SYNOPSIS
    Realiza la limpieza de archivos temporales.
#>
function Clean-TemporaryFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TemporaryDirectory,

        [Parameter()]
        [int]$MinimumAgeMinutes = 20
    )

    $removedCount = 0

    if (Test-Path -Path $TemporaryDirectory -PathType Container) {
        $cutoffTimeUtc = (Get-Date).ToUniversalTime().AddMinutes(-1 * [math]::Abs($MinimumAgeMinutes))
        foreach ($pattern in @('burst-*', 'yt-dlp-*', 'fast-cli-*', 'puppeteer_dev_chrome_profile-*', '*.tmp', '*.bak')) {
            foreach ($candidate in @(Get-ChildItem -Path $TemporaryDirectory -Filter $pattern -Force -ErrorAction SilentlyContinue)) {
                if ($candidate.LastWriteTime.ToUniversalTime() -gt $cutoffTimeUtc) {
                    continue
                }

                $candidatePath = $candidate.FullName
                Remove-PathIfExists -Path $candidatePath
                if (-not (Test-Path -Path $candidatePath)) {
                    $removedCount++
                }
            }
        }
    }

    return $removedCount
}

<#
.SYNOPSIS
    Realiza la limpieza de logs antiguos.
#>
function Clean-OldLogs {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter()]
        [int]$LogRetentionDays = 7
    )

    $removedCount = 0

    $logsPath = Join-Path -Path $RepoRoot -ChildPath 'logs'
    if (Test-Path -Path $logsPath -PathType Container) {
        $logCutoffTimeUtc = (Get-Date).ToUniversalTime().AddDays(-1 * [math]::Abs($LogRetentionDays))
        foreach ($candidate in @(Get-ChildItem -Path $logsPath -Filter '*.log' -Force -ErrorAction SilentlyContinue)) {
            if ($candidate.Name -match 'qoe-probe-\d{4}-\d{2}-\d{2}\.log' -or $candidate.Name -match 'qoe-speed-test-\d{4}-\d{2}-\d{2}\.log') {
                if ($candidate.LastWriteTime.ToUniversalTime() -gt $logCutoffTimeUtc) {
                    continue
                }

                $candidatePath = $candidate.FullName
                Remove-PathIfExists -Path $candidatePath
                if (-not (Test-Path -Path $candidatePath)) {
                    $removedCount++
                }
            }
        }
    }

    return $removedCount
}

<#
.SYNOPSIS
    Realiza la limpieza del entorno, eliminando archivos temporales y logs antiguos.
#>
function Invoke-EnvironmentGarbageCollection {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$TemporaryDirectory,

        [Parameter()]
        [int]$LogRetentionDays = 7,

        [Parameter()]
        [int]$MinimumAgeMinutes = 20
    )

    $removedCount = 0

    $removedCount += Clean-TemporaryFiles -TemporaryDirectory $TemporaryDirectory -MinimumAgeMinutes $MinimumAgeMinutes
    $removedCount += Clean-OldLogs -RepoRoot $RepoRoot -LogRetentionDays $LogRetentionDays

    return $removedCount
}

function Get-TargetHost {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target
    )

    $configuredHost = Get-OptionalStringValue -Source $Target -PropertyName 'host' -DefaultValue ''
    if (-not [string]::IsNullOrWhiteSpace($configuredHost)) {
        return $configuredHost
    }

    foreach ($propertyName in @('downloadUrl', 'videoUrl', 'url')) {
        $candidateUrl = Get-OptionalStringValue -Source $Target -PropertyName $propertyName -DefaultValue ''
        if ([string]::IsNullOrWhiteSpace($candidateUrl)) {
            continue
        }

        try {
            return ([System.Uri]$candidateUrl).Host
        }
        catch {
        }
    }

    return ''
}

function Get-TargetIsp {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Probe
    )

    $targetIsp = Get-OptionalStringValue -Source $Target -PropertyName 'isp' -DefaultValue ''
    if (-not [string]::IsNullOrWhiteSpace($targetIsp)) {
        return $targetIsp
    }

    $probeIsp = Get-OptionalStringValue -Source $Probe -PropertyName 'isp' -DefaultValue ''
    if (-not [string]::IsNullOrWhiteSpace($probeIsp)) {
        return $probeIsp
    }

    return 'unknown'
}

function Get-SpeedTestTimeoutSeconds {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun,

        [Parameter()]
        [int]$DefaultValue = 180
    )

    if ($Target.PSObject.Properties.Name -contains 'timeoutSeconds' -and $null -ne $Target.timeoutSeconds) {
        return [int]$Target.timeoutSeconds
    }

    if ($ProbeRun.PSObject.Properties.Name -contains 'speedTestTimeoutSeconds' -and $null -ne $ProbeRun.speedTestTimeoutSeconds) {
        return [int]$ProbeRun.speedTestTimeoutSeconds
    }

    return $DefaultValue
}

function Get-MbpsFromBytesAndDuration {
    param(
        [Parameter()]
        [double]$Bytes,

        [Parameter()]
        [double]$DurationMs
    )

    if ($Bytes -le 0 -or $DurationMs -le 0) {
        return 0.0
    }

    $durationSeconds = $DurationMs / 1000.0
    return [math]::Round((($Bytes * 8.0) / 1000000.0) / $durationSeconds, 2)
}

function Get-ApproximateRpmFromLatency {
    param(
        [Parameter()]
        [double]$LatencyMs
    )

    if ($LatencyMs -le 0) {
        return 0.0
    }

    return [math]::Round(60000.0 / $LatencyMs, 2)
}

function Get-PingBurstStats {
    param(
        [Parameter()]
        [string]$HostName,

        [Parameter()]
        [int]$Count = 10,

        [Parameter()]
        [int]$TimeoutMs = 1000
    )

    $result = [pscustomobject]@{
        Host = [string]$HostName
        LatencyMs = 0.0
        JitterMs = 0.0
        SuccessfulReplies = 0
        Samples = @()
    }

    if ([string]::IsNullOrWhiteSpace($HostName)) {
        return $result
    }

    $pingPath = Join-Path -Path $env:SystemRoot -ChildPath 'System32\ping.exe'
    if (-not (Test-Path -Path $pingPath -PathType Leaf)) {
        return $result
    }

    try {
        $timeoutSeconds = [math]::Max(10, [int][math]::Ceiling(($Count * $TimeoutMs) / 1000.0) + 5)
        $processResult = Invoke-ExternalProcess -CommandPath $pingPath -Arguments @('-n', [string]$Count, '-w', [string]$TimeoutMs, $HostName) -TimeoutSeconds $timeoutSeconds
        $samples = New-Object System.Collections.Generic.List[double]

        foreach ($line in ($processResult.StdOut -split "`r?`n")) {
            $timeMatch = [regex]::Match($line, '(?i)(?:time|tiempo)\s*[=<]\s*(\d+(?:\.\d+)?)\s*ms')
            if ($timeMatch.Success) {
                $samples.Add([double]$timeMatch.Groups[1].Value)
                continue
            }

            $subMillisecondMatch = [regex]::Match($line, '(?i)(?:time|tiempo)\s*<\s*1\s*ms')
            if ($subMillisecondMatch.Success) {
                $samples.Add(1.0)
            }
        }

        $latencyMs = 0.0
        if ($samples.Count -gt 0) {
            $latencyMs = [math]::Round((($samples | Measure-Object -Average).Average), 2)
        }

        $jitterMs = 0.0
        if ($samples.Count -gt 1) {
            $deltaSum = 0.0
            for ($sampleIndex = 1; $sampleIndex -lt $samples.Count; $sampleIndex++) {
                $deltaSum += [math]::Abs($samples[$sampleIndex] - $samples[$sampleIndex - 1])
            }

            $jitterMs = [math]::Round($deltaSum / ($samples.Count - 1), 2)
        }

        return [pscustomobject]@{
            Host = [string]$HostName
            LatencyMs = [double]$latencyMs
            JitterMs = [double]$jitterMs
            SuccessfulReplies = [int]$samples.Count
            Samples = @($samples)
        }
    }
    catch {
        return $result
    }
}

function Get-HttpByteRange {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RangeHeaderValue
    )

    $rangeMatch = [regex]::Match($RangeHeaderValue, '^\s*bytes\s*=\s*(\d+)(?:\s*-\s*(\d*))?\s*$')
    if (-not $rangeMatch.Success) {
        throw "Unsupported Range header value '$RangeHeaderValue'."
    }

    $rangeEnd = $null
    if ($rangeMatch.Groups[2].Success -and -not [string]::IsNullOrWhiteSpace($rangeMatch.Groups[2].Value)) {
        $rangeEnd = [int64]$rangeMatch.Groups[2].Value
    }

    return [pscustomobject]@{
        Start = [int64]$rangeMatch.Groups[1].Value
        End = $rangeEnd
    }
}

function Invoke-WebRequestToFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [Parameter(Mandatory = $true)]
        [string]$OutputPath,

        [Parameter()]
        [int]$TimeoutSeconds = 120,

        [Parameter()]
        [string]$UserAgent = '',

        [Parameter()]
        [hashtable]$Headers = @{}
    )

    $rangeHeaderValue = ''
    if ($Headers.ContainsKey('Range') -and -not [string]::IsNullOrWhiteSpace([string]$Headers['Range'])) {
        $rangeHeaderValue = [string]$Headers['Range']
    }

    if (-not [string]::IsNullOrWhiteSpace($rangeHeaderValue)) {
        $range = Get-HttpByteRange -RangeHeaderValue $rangeHeaderValue
        $request = [System.Net.HttpWebRequest][System.Net.WebRequest]::Create($Uri)
        $request.Method = 'GET'
        $request.Timeout = $TimeoutSeconds * 1000
        $request.ReadWriteTimeout = $TimeoutSeconds * 1000
        $request.AllowAutoRedirect = $true
        $request.AutomaticDecompression = [System.Net.DecompressionMethods]::GZip -bor [System.Net.DecompressionMethods]::Deflate

        if (-not [string]::IsNullOrWhiteSpace($UserAgent)) {
            $request.UserAgent = $UserAgent
        }

        foreach ($headerKey in $Headers.Keys) {
            if ($headerKey -ieq 'Range') {
                continue
            }

            $request.Headers[$headerKey] = [string]$Headers[$headerKey]
        }

        if ($null -eq $range.End) {
            $request.AddRange($range.Start)
        }
        else {
            $request.AddRange($range.Start, $range.End)
        }

        $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
        $response = $null
        $responseStream = $null
        $fileStream = $null

        try {
            $response = $request.GetResponse()
            $responseStream = $response.GetResponseStream()
            $fileStream = [System.IO.File]::Create($OutputPath)
            $responseStream.CopyTo($fileStream)
        }
        finally {
            if ($null -ne $fileStream) {
                $fileStream.Dispose()
            }

            if ($null -ne $responseStream) {
                $responseStream.Dispose()
            }

            if ($null -ne $response) {
                $response.Dispose()
            }

            $stopwatch.Stop()
        }

        return [double][math]::Round($stopwatch.Elapsed.TotalMilliseconds, 2)
    }

    $parameters = @{
        Uri = $Uri
        Method = 'Get'
        OutFile = $OutputPath
        TimeoutSec = $TimeoutSeconds
    }

    if (-not [string]::IsNullOrWhiteSpace($UserAgent)) {
        $parameters.UserAgent = $UserAgent
    }

    if ($Headers.Count -gt 0) {
        $parameters.Headers = $Headers
    }

    if ((Get-Command -Name 'Invoke-WebRequest').Parameters.ContainsKey('UseBasicParsing')) {
        $parameters.UseBasicParsing = $true
    }

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-WebRequest @parameters | Out-Null
    $stopwatch.Stop()

    return [double][math]::Round($stopwatch.Elapsed.TotalMilliseconds, 2)
}

function Get-SpeedTestUserAgent {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun
    )

    $targetUserAgent = Get-OptionalStringValue -Source $Target -PropertyName 'userAgent' -DefaultValue ''
    if (-not [string]::IsNullOrWhiteSpace($targetUserAgent)) {
        return $targetUserAgent
    }

    return (Get-OptionalStringValue -Source $ProbeRun -PropertyName 'userAgent' -DefaultValue '')
}

function Invoke-WebRequestUploadFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [Parameter(Mandatory = $true)]
        [string]$InputPath,

        [Parameter()]
        [string]$Method = 'POST',

        [Parameter()]
        [int]$TimeoutSeconds = 120
    )

    $parameters = @{
        Uri = $Uri
        Method = $Method
        InFile = $InputPath
        ContentType = 'application/octet-stream'
        TimeoutSec = $TimeoutSeconds
    }

    if ((Get-Command -Name 'Invoke-WebRequest').Parameters.ContainsKey('UseBasicParsing')) {
        $parameters.UseBasicParsing = $true
    }

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-WebRequest @parameters | Out-Null
    $stopwatch.Stop()

    return [double][math]::Round($stopwatch.Elapsed.TotalMilliseconds, 2)
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

function Get-UploadSupplementCacheKey {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [string]$UploadMeasurementMethod
    )

    switch ($UploadMeasurementMethod) {
        'networkquality' {
            return 'networkquality'
        }
        'curl-upload' {
            $uploadEndpoint = Get-OptionalStringValue -Source $Target -PropertyName 'uploadEndpoint' -DefaultValue 'https://speed.cloudflare.com/__up'
            return ('curl-upload::{0}' -f $uploadEndpoint.ToLowerInvariant())
        }
        'upload-url' {
            $uploadUrl = Get-OptionalStringValue -Source $Target -PropertyName 'uploadUrl' -DefaultValue ''
            if ([string]::IsNullOrWhiteSpace($uploadUrl)) {
                return ''
            }

            return ('upload-url::{0}' -f $uploadUrl.ToLowerInvariant())
        }
        default {
            return ''
        }
    }
}

function Invoke-UploadUrlMeasurement {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    $uploadUrl = Get-OptionalStringValue -Source $Target -PropertyName 'uploadUrl' -DefaultValue ''
    if ([string]::IsNullOrWhiteSpace($uploadUrl)) {
        throw "Target '$($Target.service)/$($Target.endpointName)' requires uploadUrl when uploadMeasurementMethod is 'upload-url'."
    }

    $transferDirectory = New-MeasurementTemporaryDirectory -PortableTools $PortableTools -Prefix 'upload-url' -Target $Target

    try {
        $uploadFilePath = Join-Path -Path $transferDirectory -ChildPath 'upload.bin'
        $timeoutSeconds = Get-SpeedTestTimeoutSeconds -Target $Target -ProbeRun $ProbeRun -DefaultValue 120
        $uploadPayloadBytes = [math]::Max(1, (Get-OptionalIntValue -Source $Target -PropertyName 'uploadPayloadBytes' -DefaultValue 1048576))
        $randomBytes = New-Object byte[] $uploadPayloadBytes
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomBytes)
        [System.IO.File]::WriteAllBytes($uploadFilePath, $randomBytes)

        $errorClass = ''
        $errorDetail = ''
        $uploadDurationMs = 0.0
        $uploadMbps = 0.0

        try {
            $uploadMethod = Get-OptionalStringValue -Source $Target -PropertyName 'uploadMethod' -DefaultValue 'POST'
            $uploadDurationMs = Invoke-WebRequestUploadFile -Uri $uploadUrl -InputPath $uploadFilePath -Method $uploadMethod -TimeoutSeconds $timeoutSeconds
            $uploadMbps = Get-MbpsFromBytesAndDuration -Bytes $uploadPayloadBytes -DurationMs $uploadDurationMs
        }
        catch {
            $errorClass = 'upload_error'
            $errorDetail = [string]$_.Exception.Message
        }

        return [pscustomobject]@{
            Tool = 'upload-url'
            UploadMbps = [double]$uploadMbps
            ErrorClass = [string]$errorClass
            ErrorDetail = [string]$errorDetail
            RunDurationMs = [double]$uploadDurationMs
        }
    }
    finally {
        Remove-PathIfExists -Path $transferDirectory
    }
}

function Invoke-CurlUploadMeasurement {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    $uploadEndpoint = Get-OptionalStringValue -Source $Target -PropertyName 'uploadEndpoint' -DefaultValue 'https://speed.cloudflare.com/__up'
    $uploadPayloadBytes = [math]::Max(1, (Get-OptionalIntValue -Source $Target -PropertyName 'uploadPayloadBytes' -DefaultValue 1048576))
    $timeoutSeconds = Get-SpeedTestTimeoutSeconds -Target $Target -ProbeRun $ProbeRun -DefaultValue 120

    $transferDirectory = New-MeasurementTemporaryDirectory -PortableTools $PortableTools -Prefix 'curl-upload' -Target $Target

    try {
        $uploadFilePath = Join-Path -Path $transferDirectory -ChildPath 'upload.bin'
        $randomBytes = New-Object byte[] $uploadPayloadBytes
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomBytes)
        [System.IO.File]::WriteAllBytes($uploadFilePath, $randomBytes)

        $errorClass = ''
        $errorDetail = ''
        $uploadDurationMs = 0.0
        $uploadMbps = 0.0

        try {
            $uploadDurationMs = Invoke-WebRequestUploadFile -Uri $uploadEndpoint -InputPath $uploadFilePath -Method 'POST' -TimeoutSeconds $timeoutSeconds
            $uploadMbps = Get-MbpsFromBytesAndDuration -Bytes $uploadPayloadBytes -DurationMs $uploadDurationMs
        }
        catch {
            $errorClass = 'upload_error'
            $errorDetail = [string]$_.Exception.Message
        }

        return [pscustomobject]@{
            Tool = 'curl-upload'
            UploadMbps = [double]$uploadMbps
            ErrorClass = [string]$errorClass
            ErrorDetail = [string]$errorDetail
            RunDurationMs = [double]$uploadDurationMs
        }
    }
    finally {
        Remove-PathIfExists -Path $transferDirectory
    }
}

function Get-UploadSupplementMeasurement {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools,

        [Parameter(Mandatory = $true)]
        [hashtable]$UploadMeasurementCache
    )

    $uploadMeasurementMethod = Get-UploadMeasurementMethod -Target $Target -ProbeRun $ProbeRun
    if ([string]::IsNullOrWhiteSpace($uploadMeasurementMethod) -or $uploadMeasurementMethod -eq 'none') {
        return $null
    }

    $cacheKey = Get-UploadSupplementCacheKey -Target $Target -UploadMeasurementMethod $uploadMeasurementMethod
    if (-not [string]::IsNullOrWhiteSpace($cacheKey) -and $UploadMeasurementCache.ContainsKey($cacheKey)) {
        return $UploadMeasurementCache[$cacheKey]
    }

    $supplementMeasurement = switch ($uploadMeasurementMethod) {
        'networkquality' {
            $networkQualityMeasurement = Get-NetworkQualityMeasurement -Target $Target -ProbeRun $ProbeRun -PortableTools $PortableTools -DisableBurstFallback
            [pscustomobject]@{
                Tool = 'networkquality'
                UploadMbps = [double]$networkQualityMeasurement.UploadMbps
                ErrorClass = [string]$networkQualityMeasurement.ErrorClass
                ErrorDetail = [string]$networkQualityMeasurement.ErrorDetail
                RunDurationMs = [double]$networkQualityMeasurement.RunDurationMs
            }
            break
        }
        'curl-upload' {
            Invoke-CurlUploadMeasurement -Target $Target -ProbeRun $ProbeRun -PortableTools $PortableTools
            break
        }
        'upload-url' {
            Invoke-UploadUrlMeasurement -Target $Target -ProbeRun $ProbeRun -PortableTools $PortableTools
            break
        }
        default {
            throw "Unsupported uploadMeasurementMethod '$uploadMeasurementMethod' for target '$($Target.service)/$($Target.endpointName)'."
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($cacheKey)) {
        $UploadMeasurementCache[$cacheKey] = $supplementMeasurement
    }

    return $supplementMeasurement
}

function Get-YtDlpBaseArguments {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    $arguments = New-Object System.Collections.Generic.List[string]
    foreach ($argument in @('--ignore-config', '--no-update', '--retries', '1', '--socket-timeout', '30')) {
        $arguments.Add([string]$argument)
    }

    if (Test-Path -Path $PortableTools.NodeExe -PathType Leaf) {
        $arguments.Add('--no-js-runtimes')
        $arguments.Add('--js-runtimes')
        $arguments.Add("node:$($PortableTools.NodeExe)")
    }

    return @($arguments)
}

function Test-FastCliNavigationTimeout {
    param(
        [Parameter()]
        [string]$Output
    )

    return (-not [string]::IsNullOrWhiteSpace($Output) -and $Output -match 'Navigation timeout of [0-9]+ ms exceeded')
}

function Patch-FastCliTimeout {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FastCliScriptPath
    )

    if (-not (Test-Path -Path $FastCliScriptPath -PathType Leaf)) {
        return
    }

    $apiJsPath = Join-Path -Path (Split-Path -Path $FastCliScriptPath -Parent) -ChildPath 'api.js'
    if (Test-Path -Path $apiJsPath -PathType Leaf) {
        $content = Get-Content -Path $apiJsPath -Raw
        $modified = $false

        if ($content -match 'timeoutMs\s*=\s*(90000|240000|390000)') {
            Write-Verbose "Patching fast-cli timeout to 390s in $apiJsPath"
            $content = $content -replace 'timeoutMs\s*=\s*(90000|240000|390000)', 'timeoutMs = 390000'
            $modified = $true
        }

        if ($content -notlike '*AutomationControlled*') {
            Write-Verbose "Patching fast-cli to disable automation detection in $apiJsPath"
            $content = $content -replace "'--ignore-certificate-errors'", "'--ignore-certificate-errors', '--disable-blink-features=AutomationControlled'"
            $modified = $true
        }

        if ($content -notlike '*setUserAgent*') {
            Write-Verbose "Patching fast-cli to use a real User Agent in $apiJsPath"
            $userAgentStr = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            $content = $content -replace 'const page = await browser.newPage\(\);', "const page = await browser.newPage();`n    await page.setUserAgent('$userAgentStr');"
            $modified = $true
        }

        if ($modified) {
            Set-Content -Path $apiJsPath -Value $content -Force
        }
    }
}

function Invoke-FastCliMeasurement {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    if (-not (Test-Path -Path $PortableTools.NodeExe -PathType Leaf)) {
        throw "Portable Node.js was not found at '$($PortableTools.NodeExe)'."
    }

    if (-not (Test-Path -Path $PortableTools.FastCliScript -PathType Leaf)) {
        throw "fast-cli entrypoint was not found at '$($PortableTools.FastCliScript)'."
    }

    Ensure-DirectoryExists -Path $PortableTools.PuppeteerCacheDir

    Patch-FastCliTimeout -FastCliScriptPath $PortableTools.FastCliScript

    try {
        $environmentVariables = @{
            PUPPETEER_CACHE_DIR = $PortableTools.PuppeteerCacheDir
        }

        $timeoutSeconds = Get-SpeedTestTimeoutSeconds -Target $Target -ProbeRun $ProbeRun -DefaultValue 180
        $fastCliAttemptCount = [math]::Max(1, (Get-OptionalIntValue -Source $Target -PropertyName 'fastCliAttemptCount' -DefaultValue (Get-OptionalIntValue -Source $ProbeRun -PropertyName 'fastCliAttemptCount' -DefaultValue 2)))
        $processResult = $null
        $combinedProcessOutput = ''

        for ($attempt = 1; $attempt -le $fastCliAttemptCount; $attempt++) {
            $processResult = Invoke-ExternalProcess -CommandPath $PortableTools.NodeExe -Arguments @($PortableTools.FastCliScript, '--upload', '--json') -TimeoutSeconds $timeoutSeconds -EnvironmentVariables $environmentVariables -WorkingDirectory (Split-Path -Path $PortableTools.FastCliScript -Parent)
            $combinedProcessOutput = if (-not [string]::IsNullOrWhiteSpace($processResult.StdErr)) { $processResult.StdErr } else { $processResult.StdOut }

            $isRetryableNavigationTimeout = (-not $processResult.TimedOut) -and ($processResult.ExitCode -ne 0) -and (Test-FastCliNavigationTimeout -Output $combinedProcessOutput)
            if (-not $isRetryableNavigationTimeout -or $attempt -eq $fastCliAttemptCount) {
                break
            }
        }

        $errorClass = ''
        $errorDetail = ''
        $parsedJson = $null

        if ($processResult.TimedOut) {
            $errorClass = 'timeout'
            $errorDetail = 'fast-cli timed out.'
        }
        elseif ($processResult.ExitCode -ne 0) {
            $errorDetail = [string]$combinedProcessOutput
            if (Test-FastCliNavigationTimeout -Output $errorDetail) {
                $errorClass = 'timeout'
            }
            else {
                $errorClass = 'cli_error'
            }
        }
        else {
            $jsonPayload = Get-JsonPayloadFromText -Text $processResult.StdOut
            if ([string]::IsNullOrWhiteSpace($jsonPayload)) {
                $errorClass = 'parse_error'
                $errorDetail = 'fast-cli did not return JSON output.'
            }
            else {
                try {
                    $parsedJson = $jsonPayload | ConvertFrom-Json -ErrorAction Stop
                }
                catch {
                    $errorClass = 'parse_error'
                    $errorDetail = [string]$_.Exception.Message
                }
            }
        }

        $pingStats = Get-PingBurstStats -HostName (Get-TargetHost -Target $Target)
        $latencyMs = [math]::Round((ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsedJson -Path @('latency')) -DefaultValue $pingStats.LatencyMs), 2)

        return [pscustomobject]@{
            Tool = 'fast-cli'
            ExitCode = [int]$processResult.ExitCode
            TimedOut = [bool]$processResult.TimedOut
            DownloadMbps = [math]::Round((ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsedJson -Path @('downloadSpeed'))), 2)
            UploadMbps = [math]::Round((ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsedJson -Path @('uploadSpeed'))), 2)
            LatencyMs = [double]$latencyMs
            JitterMs = [double]$pingStats.JitterMs
            RpmResponsiveness = [double](Get-ApproximateRpmFromLatency -LatencyMs $latencyMs)
            SourceHost = [string](Get-TargetHost -Target $Target)
            ErrorClass = [string]$errorClass
            ErrorDetail = [string]$errorDetail
            RawStdOut = [string]$processResult.StdOut
            RawStdErr = [string]$processResult.StdErr
            RunDurationMs = [double]$processResult.DurationMs
            Available = [bool]([string]::IsNullOrWhiteSpace($errorClass) -and $processResult.ExitCode -eq 0)
        }
    }
    finally {
        if ($null -ne $PortableTools -and -not [string]::IsNullOrWhiteSpace($PortableTools.PuppeteerCacheDir)) {
            $puppeteerCachePath = $PortableTools.PuppeteerCacheDir
            Get-Process -Name 'chrome', 'chrome-headless-shell' -ErrorAction SilentlyContinue |
                Where-Object { $null -ne $_.Path -and $_.Path.StartsWith($puppeteerCachePath, [System.StringComparison]::OrdinalIgnoreCase) } |
                Stop-Process -Force -ErrorAction SilentlyContinue
        }
    }
}

function Resolve-YtDlpDirectHost {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    $directUrl = Resolve-YtDlpDirectUrl -Target $Target -PortableTools $PortableTools
    if ([string]::IsNullOrWhiteSpace($directUrl)) {
        return (Get-TargetHost -Target $Target)
    }

    try {
        return ([System.Uri]$directUrl).Host
    }
    catch {
        return (Get-TargetHost -Target $Target)
    }
}

function Resolve-YtDlpDirectUrl {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    $videoUrl = Get-OptionalStringValue -Source $Target -PropertyName 'videoUrl' -DefaultValue (Get-OptionalStringValue -Source $Target -PropertyName 'url' -DefaultValue '')
    if ([string]::IsNullOrWhiteSpace($videoUrl) -or -not (Test-Path -Path $PortableTools.YtDlpExe -PathType Leaf)) {
        return ''
    }

    if (-not ($videoUrl.StartsWith('http://', [System.StringComparison]::OrdinalIgnoreCase) -or $videoUrl.StartsWith('https://', [System.StringComparison]::OrdinalIgnoreCase))) {
        return ''
    }

    $arguments = New-Object System.Collections.Generic.List[string]
    foreach ($argument in (Get-YtDlpBaseArguments -PortableTools $PortableTools)) {
        $arguments.Add([string]$argument)
    }

    $formatSelector = Get-OptionalStringValue -Source $Target -PropertyName 'format' -DefaultValue 'best[protocol^=https][height<=480]/best[height<=480]/best'
    foreach ($argument in @('--print', 'urls', '--format', $formatSelector, '--', $videoUrl)) {
        $arguments.Add([string]$argument)
    }

    $processResult = Invoke-ExternalProcess -CommandPath $PortableTools.YtDlpExe -Arguments @($arguments) -TimeoutSeconds 60 -WorkingDirectory $PortableTools.RepoRoot
    foreach ($line in ($processResult.StdOut -split "`r?`n")) {
        $trimmedLine = $line.Trim()
        if ($trimmedLine -like 'http*') {
            return $trimmedLine
        }
    }

    return ''
}

function Invoke-YtDlpMeasurement {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    if (-not (Test-Path -Path $PortableTools.YtDlpExe -PathType Leaf)) {
        throw "yt-dlp.exe was not found at '$($PortableTools.YtDlpExe)'."
    }

    $videoUrl = Get-OptionalStringValue -Source $Target -PropertyName 'videoUrl' -DefaultValue (Get-OptionalStringValue -Source $Target -PropertyName 'url' -DefaultValue '')
    if ([string]::IsNullOrWhiteSpace($videoUrl)) {
        throw "Speed-test target '$($Target.service)/$($Target.endpointName)' requires videoUrl when speedTestMethod is 'yt-dlp'."
    }

    if (-not ($videoUrl.StartsWith('http://', [System.StringComparison]::OrdinalIgnoreCase) -or $videoUrl.StartsWith('https://', [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "Speed-test target '$($Target.service)/$($Target.endpointName)' requires videoUrl to start with 'http://' or 'https://'."
    }

    $downloadDirectory = New-MeasurementTemporaryDirectory -PortableTools $PortableTools -Prefix 'yt-dlp' -Target $Target

    try {
        $timeoutSeconds = Get-SpeedTestTimeoutSeconds -Target $Target -ProbeRun $ProbeRun -DefaultValue 180
        $directMediaUrl = Resolve-YtDlpDirectUrl -Target $Target -PortableTools $PortableTools
        $sourceHost = Resolve-YtDlpDirectHost -Target $Target -PortableTools $PortableTools
        $pingStats = Get-PingBurstStats -HostName $sourceHost

        $errorClass = ''
        $errorDetail = ''
        $downloadDurationMs = 0.0
        $downloadBytes = 0.0
        $fragmentFilePath = Join-Path -Path $downloadDirectory -ChildPath 'probe-fragment.bin'
        if ([string]::IsNullOrWhiteSpace($directMediaUrl)) {
            $errorClass = 'resolve_error'
            $errorDetail = 'yt-dlp did not return a direct media URL.'
        }
        else {
            try {
                $fragmentBytes = 4194304
                if ($Target.PSObject.Properties.Name -contains 'fragmentBytes' -and $null -ne $Target.fragmentBytes) {
                    $fragmentBytes = [int]$Target.fragmentBytes
                }

                $downloadDurationMs = Invoke-WebRequestToFile -Uri $directMediaUrl -OutputPath $fragmentFilePath -TimeoutSeconds $timeoutSeconds -Headers @{ Range = ('bytes=0-{0}' -f ($fragmentBytes - 1)) }
                if (Test-Path -Path $fragmentFilePath -PathType Leaf) {
                    $downloadBytes = [double](Get-Item -Path $fragmentFilePath).Length
                }
            }
            catch {
                $errorClass = 'download_error'
                $errorDetail = [string]$_.Exception.Message
            }
        }

        $downloadMbps = Get-MbpsFromBytesAndDuration -Bytes $downloadBytes -DurationMs $downloadDurationMs
        if ([string]::IsNullOrWhiteSpace($errorClass) -and $downloadBytes -le 0) {
            $errorClass = 'download_empty'
            $errorDetail = 'yt-dlp resolved the media URL but the fragment download wrote no bytes.'
        }

        return [pscustomobject]@{
            Tool = 'yt-dlp'
            ExitCode = if ([string]::IsNullOrWhiteSpace($errorClass)) { 0 } else { -1 }
            TimedOut = $false
            DownloadMbps = [double]$downloadMbps
            UploadMbps = 0.0
            LatencyMs = [double]$pingStats.LatencyMs
            JitterMs = [double]$pingStats.JitterMs
            RpmResponsiveness = [double](Get-ApproximateRpmFromLatency -LatencyMs $pingStats.LatencyMs)
            SourceHost = [string]$sourceHost
            ErrorClass = [string]$errorClass
            ErrorDetail = [string]$errorDetail
            RawStdOut = [string]$directMediaUrl
            RawStdErr = ''
            RunDurationMs = [double]$downloadDurationMs
            Available = [bool]([string]::IsNullOrWhiteSpace($errorClass) -and $downloadBytes -gt 0)
        }
    }
    finally {
        Remove-PathIfExists -Path $downloadDirectory
    }
}

function Resolve-NetworkQualityExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    $configuredPath = Get-OptionalStringValue -Source $Target -PropertyName 'commandPath' -DefaultValue ''
    if ([string]::IsNullOrWhiteSpace($configuredPath)) {
        $configuredPath = [string]$PortableTools.NetworkQualityExe
    }

    if ([string]::IsNullOrWhiteSpace($configuredPath)) {
        return ''
    }

    if ([System.IO.Path]::IsPathRooted($configuredPath)) {
        if (Test-Path -Path $configuredPath -PathType Leaf) {
            return [System.IO.Path]::GetFullPath($configuredPath)
        }

        return ''
    }

    $candidatePath = Get-FullPathFromBase -BasePath $PortableTools.RepoRoot -ChildPath $configuredPath
    if (Test-Path -Path $candidatePath -PathType Leaf) {
        return [System.IO.Path]::GetFullPath($candidatePath)
    }

    return ''
}

function Get-FirstRegexDouble {
    param(
        [Parameter()]
        [string]$Text,

        [Parameter(Mandatory = $true)]
        [string[]]$Patterns
    )

    foreach ($pattern in $Patterns) {
        $match = [regex]::Match($Text, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase -bor [System.Text.RegularExpressions.RegexOptions]::Multiline)
        if ($match.Success) {
            return [math]::Round((ConvertTo-DoubleOrDefault -Value $match.Groups[1].Value), 2)
        }
    }

    return 0.0
}

function Get-FirstBandwidthMbps {
    param(
        [Parameter()]
        [string]$Text,

        [Parameter(Mandatory = $true)]
        [string[]]$Patterns
    )

    foreach ($pattern in $Patterns) {
        $match = [regex]::Match($Text, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase -bor [System.Text.RegularExpressions.RegexOptions]::Multiline)
        if ($match.Success) {
            $numericValue = ConvertTo-DoubleOrDefault -Value $match.Groups[1].Value
            $unitValue = (ConvertTo-StringOrDefault -Value $match.Groups[2].Value -DefaultValue 'Mbps').ToLowerInvariant()

            if ($unitValue -match '^g') {
                return [math]::Round($numericValue * 1000.0, 2)
            }

            if ($unitValue -match '^k') {
                return [math]::Round($numericValue / 1000.0, 2)
            }

            if ($unitValue -match '^b') {
                return [math]::Round($numericValue / 1000000.0, 2)
            }

            return [math]::Round($numericValue, 2)
        }
    }

    return 0.0
}

function Invoke-BurstTrafficMeasurement {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools
    )

    $downloadUrl = Get-OptionalStringValue -Source $Target -PropertyName 'downloadUrl' -DefaultValue (Get-OptionalStringValue -Source $Target -PropertyName 'url' -DefaultValue '')
    if ([string]::IsNullOrWhiteSpace($downloadUrl)) {
        throw "Speed-test target '$($Target.service)/$($Target.endpointName)' requires downloadUrl or url when speedTestMethod is 'burst'."
    }

    $transferDirectory = New-MeasurementTemporaryDirectory -PortableTools $PortableTools -Prefix 'burst' -Target $Target

    try {
        $uploadFilePath = Join-Path -Path $transferDirectory -ChildPath 'upload.bin'
        $timeoutSeconds = Get-SpeedTestTimeoutSeconds -Target $Target -ProbeRun $ProbeRun -DefaultValue 120
        $userAgent = Get-SpeedTestUserAgent -Target $Target -ProbeRun $ProbeRun
        $targetTransferBytes = [math]::Max(0, (Get-OptionalIntValue -Source $Target -PropertyName 'targetTransferBytes' -DefaultValue 0))
        $maxDownloadIterationsDefault = if ($targetTransferBytes -gt 0) { 8 } else { 1 }
        $maxDownloadIterations = [math]::Max(1, (Get-OptionalIntValue -Source $Target -PropertyName 'maxDownloadIterations' -DefaultValue $maxDownloadIterationsDefault))

        $errorClass = ''
        $errorDetail = ''
        $downloadDurationMs = 0.0
        $uploadDurationMs = 0.0
        $downloadBytes = 0.0
        $downloadAttemptCount = 0
        $downloadStopwatch = [System.Diagnostics.Stopwatch]::StartNew()

        try {
            do {
                $remainingSeconds = [math]::Max(1, [int][math]::Floor($timeoutSeconds - $downloadStopwatch.Elapsed.TotalSeconds))
                if ($remainingSeconds -le 0) {
                    $errorClass = 'timeout'
                    $errorDetail = 'burst download timed out before collecting the requested sample size.'
                    break
                }

                $downloadAttemptCount++
                $downloadFilePath = Join-Path -Path $transferDirectory -ChildPath ('download-{0}.bin' -f $downloadAttemptCount)

                $headers = @{}
                if ($targetTransferBytes -gt 0) {
                    $bytesToRequest = $targetTransferBytes - $downloadBytes
                    if ($bytesToRequest -gt 0) {
                        $headers['Range'] = 'bytes=0-{0}' -f [int64]($bytesToRequest - 1)
                    }
                }

                $attemptDurationMs = Invoke-WebRequestToFile -Uri $downloadUrl -OutputPath $downloadFilePath -TimeoutSeconds $remainingSeconds -UserAgent $userAgent -Headers $headers
                $attemptBytes = if (Test-Path -Path $downloadFilePath -PathType Leaf) { [double](Get-Item -Path $downloadFilePath).Length } else { 0.0 }

                $downloadDurationMs += $attemptDurationMs
                $downloadBytes += $attemptBytes
                Remove-PathIfExists -Path $downloadFilePath

                if ($attemptBytes -le 0) {
                    break
                }
            }
            while (
                [string]::IsNullOrWhiteSpace($errorClass) -and
                $targetTransferBytes -gt 0 -and
                $downloadBytes -lt $targetTransferBytes -and
                $downloadAttemptCount -lt $maxDownloadIterations
            )
        }
        catch {
            $errorClass = 'download_error'
            $errorDetail = [string]$_.Exception.Message
        }
        finally {
            $downloadStopwatch.Stop()
        }

        $downloadMbps = Get-MbpsFromBytesAndDuration -Bytes $downloadBytes -DurationMs $downloadDurationMs
        $uploadMbps = 0.0

        $uploadUrl = Get-OptionalStringValue -Source $Target -PropertyName 'uploadUrl' -DefaultValue ''
        if ([string]::IsNullOrWhiteSpace($errorClass) -and -not [string]::IsNullOrWhiteSpace($uploadUrl)) {
            try {
                $uploadPayloadBytes = 1048576
                if ($Target.PSObject.Properties.Name -contains 'uploadPayloadBytes' -and $null -ne $Target.uploadPayloadBytes) {
                    $uploadPayloadBytes = [int]$Target.uploadPayloadBytes
                }

                $randomBytes = New-Object byte[] $uploadPayloadBytes
                [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($randomBytes)
                [System.IO.File]::WriteAllBytes($uploadFilePath, $randomBytes)

                $uploadMethod = Get-OptionalStringValue -Source $Target -PropertyName 'uploadMethod' -DefaultValue 'POST'
                $uploadDurationMs = Invoke-WebRequestUploadFile -Uri $uploadUrl -InputPath $uploadFilePath -Method $uploadMethod -TimeoutSeconds $timeoutSeconds
                $uploadMbps = Get-MbpsFromBytesAndDuration -Bytes $uploadPayloadBytes -DurationMs $uploadDurationMs
            }
            catch {
                $errorClass = 'upload_error'
                $errorDetail = [string]$_.Exception.Message
            }
        }

        $sourceHost = Get-TargetHost -Target $Target
        $pingStats = Get-PingBurstStats -HostName $sourceHost
        $latencyMs = [double]$pingStats.LatencyMs
        $rpmResponsiveness = Get-ApproximateRpmFromLatency -LatencyMs $latencyMs

        return [pscustomobject]@{
            Tool = 'burst'
            ExitCode = if ([string]::IsNullOrWhiteSpace($errorClass)) { 0 } else { -1 }
            TimedOut = $false
            DownloadMbps = [double]$downloadMbps
            UploadMbps = [double]$uploadMbps
            LatencyMs = [double]$latencyMs
            JitterMs = [double]$pingStats.JitterMs
            RpmResponsiveness = [double]$rpmResponsiveness
            SourceHost = [string]$sourceHost
            ErrorClass = [string]$errorClass
            ErrorDetail = [string]$errorDetail
            RawStdOut = ('download_attempts={0};download_bytes={1};target_transfer_bytes={2};download_url={3}' -f $downloadAttemptCount, [int64]$downloadBytes, $targetTransferBytes, $downloadUrl)
            RawStdErr = ''
            RunDurationMs = [double]([math]::Round(($downloadDurationMs + $uploadDurationMs), 2))
            Available = [bool]([string]::IsNullOrWhiteSpace($errorClass) -and ($downloadBytes -gt 0 -or $uploadMbps -gt 0))
        }
    }
    finally {
        Remove-PathIfExists -Path $transferDirectory
    }
}

function Get-NetworkQualityMeasurement {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$ProbeRun,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools,

        [Parameter()]
        [switch]$DisableBurstFallback
    )

    $commandPath = Resolve-NetworkQualityExecutable -Target $Target -PortableTools $PortableTools
    if ([string]::IsNullOrWhiteSpace($commandPath)) {
        if ($DisableBurstFallback) {
            throw "networkquality.exe was not found for target '$($Target.service)/$($Target.endpointName)'."
        }

        return Invoke-BurstTrafficMeasurement -Target $Target -ProbeRun $ProbeRun -PortableTools $PortableTools
    }

    $arguments = New-Object System.Collections.Generic.List[string]
    if ($Target.PSObject.Properties.Name -contains 'arguments' -and $null -ne $Target.arguments) {
        foreach ($argument in @($Target.arguments)) {
            if (-not [string]::IsNullOrWhiteSpace([string]$argument)) {
                $arguments.Add([string]$argument)
            }
        }
    }

    $timeoutSeconds = Get-SpeedTestTimeoutSeconds -Target $Target -ProbeRun $ProbeRun -DefaultValue 180
    $processResult = Invoke-ExternalProcess -CommandPath $commandPath -Arguments @($arguments) -TimeoutSeconds $timeoutSeconds -WorkingDirectory $PortableTools.RepoRoot

    $combinedOutput = (($processResult.StdOut, $processResult.StdErr | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join "`n").Trim()
    $parsedJson = $null
    $jsonPayload = Get-JsonPayloadFromText -Text $combinedOutput
    if (-not [string]::IsNullOrWhiteSpace($jsonPayload)) {
        try {
            $parsedJson = $jsonPayload | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            $parsedJson = $null
        }
    }

    $downloadMbps = ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsedJson -Path @('downloadMbps'))
    if ($downloadMbps -le 0) {
        $downloadMbps = Get-FirstBandwidthMbps -Text $combinedOutput -Patterns @('Download(?:\s+capacity)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]+)', 'Down(?:link)?(?:\s+bandwidth)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]+)')
    }

    $uploadMbps = ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsedJson -Path @('uploadMbps'))
    if ($uploadMbps -le 0) {
        $uploadMbps = Get-FirstBandwidthMbps -Text $combinedOutput -Patterns @('Upload(?:\s+capacity)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]+)', 'Up(?:link)?(?:\s+bandwidth)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]+)')
    }

    $pingStats = Get-PingBurstStats -HostName (Get-TargetHost -Target $Target)
    $latencyMs = ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsedJson -Path @('latencyMs'))
    if ($latencyMs -le 0) {
        $latencyMs = Get-FirstRegexDouble -Text $combinedOutput -Patterns @('(?:Idle\s+)?Latency\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*ms', 'Round\s*trip\s*latency\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*ms')
    }
    if ($latencyMs -le 0) {
        $latencyMs = [double]$pingStats.LatencyMs
    }

    $rpmResponsiveness = ConvertTo-DoubleOrDefault -Value (Get-NestedPropertyValue -Object $parsedJson -Path @('rpmResponsiveness'))
    if ($rpmResponsiveness -le 0) {
        $rpmResponsiveness = Get-FirstRegexDouble -Text $combinedOutput -Patterns @('Responsiveness\s*:\s*.*?\(([0-9]+(?:\.[0-9]+)?)\s*RPM\)', 'RPM(?:\s+Responsiveness)?\s*:\s*([0-9]+(?:\.[0-9]+)?)')
    }
    if ($rpmResponsiveness -le 0) {
        $rpmResponsiveness = Get-ApproximateRpmFromLatency -LatencyMs $latencyMs
    }

    $errorClass = ''
    $errorDetail = ''
    if ($processResult.TimedOut) {
        $errorClass = 'timeout'
        $errorDetail = 'networkquality timed out.'
    }
    elseif ($processResult.ExitCode -ne 0) {
        $errorClass = 'cli_error'
        $errorDetail = if (-not [string]::IsNullOrWhiteSpace($processResult.StdErr)) { $processResult.StdErr } else { $processResult.StdOut }
    }
    elseif ($downloadMbps -le 0 -and $uploadMbps -le 0 -and $rpmResponsiveness -le 0) {
        $errorClass = 'parse_error'
        $errorDetail = 'networkquality output did not contain recognizable throughput or responsiveness metrics.'
    }

    return [pscustomobject]@{
        Tool = 'networkquality'
        ExitCode = [int]$processResult.ExitCode
        TimedOut = [bool]$processResult.TimedOut
        DownloadMbps = [double][math]::Round($downloadMbps, 2)
        UploadMbps = [double][math]::Round($uploadMbps, 2)
        LatencyMs = [double][math]::Round($latencyMs, 2)
        JitterMs = [double]$pingStats.JitterMs
        RpmResponsiveness = [double][math]::Round($rpmResponsiveness, 2)
        SourceHost = [string](Get-TargetHost -Target $Target)
        ErrorClass = [string]$errorClass
        ErrorDetail = [string]$errorDetail
        RawStdOut = [string]$processResult.StdOut
        RawStdErr = [string]$processResult.StdErr
        RunDurationMs = [double]$processResult.DurationMs
        Available = [bool]([string]::IsNullOrWhiteSpace($errorClass) -and $processResult.ExitCode -eq 0)
    }
}

function Get-SpeedTestFailureTargetResult {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config,

        [Parameter(Mandatory = $true)]
        [string]$ErrorMessage,

        [Parameter(Mandatory = $true)]
        [double]$RunDurationMs
    )

    $isp = Get-TargetIsp -Target $Target -Probe $Config.probe
    $speedTestMethod = (Get-OptionalStringValue -Source $Target -PropertyName 'speedTestMethod' -DefaultValue 'unknown').ToLowerInvariant()
    $sourceHost = Get-TargetHost -Target $Target
    $measurementName = Get-OptionalStringValue -Source $Config.probeRun -PropertyName 'realMetricsMeasurement' -DefaultValue 'qoe_real_metrics'

    $fields = @{
        download_speed = 0.0
        upload_speed = 0.0
        upload_tool = 'none'
        upload_error_class = ''
        upload_error_detail = ''
        latency = 0.0
        jitter = 0.0
        rpm_responsiveness = 0.0
        endpoint_name = [string]$Target.endpointName
        target_type = 'speedtest'
        speed_test_method = [string]$speedTestMethod
        tool = [string]$speedTestMethod
        available = $false
        source_host = [string]$sourceHost
        error_class = 'probe_exception'
        error_detail = [string]$ErrorMessage
        run_duration_ms = [double]$RunDurationMs
    }

    $report = [pscustomobject]@{
        service = [string]$Target.service
        endpoint_name = [string]$Target.endpointName
        type = 'speedtest'
        speed_test_method = [string]$speedTestMethod
        available = $false
        download_mbps = 0.0
        upload_mbps = 0.0
        upload_tool = 'none'
        upload_error_class = ''
        upload_error_detail = ''
        latency_ms = 0.0
        jitter_ms = 0.0
        rpm_responsiveness = 0.0
        isp = [string]$isp
        source_host = [string]$sourceHost
        error_class = 'probe_exception'
        error_detail = [string]$ErrorMessage
        run_duration_ms = [double]$RunDurationMs
    }

    return [pscustomobject]@{
        Measurement = [string]$measurementName
        Tags = @{
            service = [string]$Target.service
            probe_id = [string]$Config.probe.probeId
            isp = [string]$isp
        }
        Fields = $fields
        Report = $report
        Available = $false
        LogMessage = ("Target {0}/{1} failed: {2}" -f $Target.service, $Target.endpointName, $ErrorMessage)
    }
}

function Invoke-SpeedTestTarget {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject]$Target,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$Config,

        [Parameter(Mandatory = $true)]
        [pscustomobject]$PortableTools,

        [Parameter(Mandatory = $true)]
        [hashtable]$UploadMeasurementCache
    )

    $speedTestMethod = (Get-OptionalStringValue -Source $Target -PropertyName 'speedTestMethod' -DefaultValue '').ToLowerInvariant()
    switch ($speedTestMethod) {
        'fast-cli' {
            $measurementResult = Invoke-FastCliMeasurement -Target $Target -ProbeRun $Config.probeRun -PortableTools $PortableTools
            break
        }
        'yt-dlp' {
            $measurementResult = Invoke-YtDlpMeasurement -Target $Target -ProbeRun $Config.probeRun -PortableTools $PortableTools
            break
        }
        'networkquality' {
            $measurementResult = Get-NetworkQualityMeasurement -Target $Target -ProbeRun $Config.probeRun -PortableTools $PortableTools
            break
        }
        'burst' {
            $measurementResult = Invoke-BurstTrafficMeasurement -Target $Target -ProbeRun $Config.probeRun -PortableTools $PortableTools
            break
        }
        default {
            throw "Unsupported speedTestMethod '$speedTestMethod' for target '$($Target.service)/$($Target.endpointName)'."
        }
    }

    $uploadTool = if ([double]$measurementResult.UploadMbps -gt 0) {
        if ([string]$measurementResult.Tool -eq 'burst' -and -not [string]::IsNullOrWhiteSpace((Get-OptionalStringValue -Source $Target -PropertyName 'uploadUrl' -DefaultValue ''))) {
            'upload-url'
        }
        else {
            [string]$measurementResult.Tool
        }
    }
    else {
        'none'
    }

    $uploadErrorClass = ''
    $uploadErrorDetail = ''

    if ($measurementResult.Available -and [double]$measurementResult.UploadMbps -le 0) {
        try {
            $supplementMeasurement = Get-UploadSupplementMeasurement -Target $Target -ProbeRun $Config.probeRun -PortableTools $PortableTools -UploadMeasurementCache $UploadMeasurementCache
            if ($null -ne $supplementMeasurement) {
                $measurementResult.RunDurationMs = [double][math]::Round(($measurementResult.RunDurationMs + $supplementMeasurement.RunDurationMs), 2)
                $uploadTool = [string]$supplementMeasurement.Tool

                if ([double]$supplementMeasurement.UploadMbps -gt 0 -and [string]::IsNullOrWhiteSpace((ConvertTo-StringOrDefault -Value $supplementMeasurement.ErrorClass -DefaultValue ''))) {
                    $measurementResult.UploadMbps = [double]$supplementMeasurement.UploadMbps
                }
                else {
                    $uploadErrorClass = ConvertTo-StringOrDefault -Value $supplementMeasurement.ErrorClass -DefaultValue 'upload_unavailable'
                    $uploadErrorDetail = ConvertTo-StringOrDefault -Value $supplementMeasurement.ErrorDetail -DefaultValue 'Upload supplement did not return throughput.'
                }
            }
        }
        catch {
            $uploadTool = Get-UploadMeasurementMethod -Target $Target -ProbeRun $Config.probeRun
            if ([string]::IsNullOrWhiteSpace($uploadTool)) {
                $uploadTool = 'none'
            }

            $uploadErrorClass = 'upload_measurement_error'
            $uploadErrorDetail = [string]$_.Exception.Message
        }
    }

    $isp = Get-TargetIsp -Target $Target -Probe $Config.probe
    $measurementName = Get-OptionalStringValue -Source $Config.probeRun -PropertyName 'realMetricsMeasurement' -DefaultValue 'qoe_real_metrics'

    $fields = @{
        download_speed = [double]$measurementResult.DownloadMbps
        upload_speed = [double]$measurementResult.UploadMbps
        upload_tool = [string]$uploadTool
        upload_error_class = [string]$uploadErrorClass
        upload_error_detail = [string]$uploadErrorDetail
        latency = [double]$measurementResult.LatencyMs
        jitter = [double]$measurementResult.JitterMs
        rpm_responsiveness = [double]$measurementResult.RpmResponsiveness
        endpoint_name = [string]$Target.endpointName
        target_type = 'speedtest'
        speed_test_method = [string]$speedTestMethod
        tool = [string]$measurementResult.Tool
        available = [bool]$measurementResult.Available
        source_host = [string]$measurementResult.SourceHost
        error_class = [string]$measurementResult.ErrorClass
        error_detail = [string]$measurementResult.ErrorDetail
        run_duration_ms = [double]$measurementResult.RunDurationMs
    }

    $report = [pscustomobject]@{
        service = [string]$Target.service
        endpoint_name = [string]$Target.endpointName
        type = 'speedtest'
        speed_test_method = [string]$speedTestMethod
        available = [bool]$measurementResult.Available
        download_mbps = [double]$measurementResult.DownloadMbps
        upload_mbps = [double]$measurementResult.UploadMbps
        upload_tool = [string]$uploadTool
        upload_error_class = [string]$uploadErrorClass
        upload_error_detail = [string]$uploadErrorDetail
        latency_ms = [double]$measurementResult.LatencyMs
        jitter_ms = [double]$measurementResult.JitterMs
        rpm_responsiveness = [double]$measurementResult.RpmResponsiveness
        isp = [string]$isp
        source_host = [string]$measurementResult.SourceHost
        error_class = [string]$measurementResult.ErrorClass
        error_detail = [string]$measurementResult.ErrorDetail
        run_duration_ms = [double]$measurementResult.RunDurationMs
    }

    return [pscustomobject]@{
        Measurement = [string]$measurementName
        Tags = @{
            service = [string]$Target.service
            probe_id = [string]$Config.probe.probeId
            isp = [string]$isp
        }
        Fields = $fields
        Report = $report
        Available = [bool]$measurementResult.Available
        LogMessage = if ($measurementResult.Available) {
            if (-not [string]::IsNullOrWhiteSpace($uploadErrorClass)) {
                "Target {0}/{1} completed with download {2} Mbps, upload {3} Mbps via {4}, latency {5} ms, jitter {6} ms, rpm {7}, tool {8}, upload_error_class {9}: {10}" -f $Target.service, $Target.endpointName, $measurementResult.DownloadMbps, $measurementResult.UploadMbps, $uploadTool, $measurementResult.LatencyMs, $measurementResult.JitterMs, $measurementResult.RpmResponsiveness, $measurementResult.Tool, $uploadErrorClass, $uploadErrorDetail
            }
            else {
                "Target {0}/{1} completed with download {2} Mbps, upload {3} Mbps via {4}, latency {5} ms, jitter {6} ms, rpm {7}, tool {8}" -f $Target.service, $Target.endpointName, $measurementResult.DownloadMbps, $measurementResult.UploadMbps, $uploadTool, $measurementResult.LatencyMs, $measurementResult.JitterMs, $measurementResult.RpmResponsiveness, $measurementResult.Tool
            }
        }
        else {
            "Target {0}/{1} completed with error_class {2}: {3}" -f $Target.service, $Target.endpointName, (ConvertTo-StringOrDefault -Value $measurementResult.ErrorClass -DefaultValue 'unavailable'), (ConvertTo-StringOrDefault -Value $measurementResult.ErrorDetail -DefaultValue 'No additional detail was provided.')
        }
    }
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
$repoRoot = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..'
$resolvedRunReportPath = ''
if (-not [string]::IsNullOrWhiteSpace($RunReportPath)) {
    $resolvedRunReportPath = Get-FullPathFromBase -BasePath $repoRoot -ChildPath $RunReportPath
}

$logDirectoryConfig = $config.probeRun.logDirectory
if ([string]::IsNullOrWhiteSpace($logDirectoryConfig)) {
    $logDirectoryConfig = 'logs'
}

$logDirectory = Get-FullPathFromBase -BasePath $repoRoot -ChildPath $logDirectoryConfig

$repoRootWithSeparator = $repoRoot
if (-not $repoRootWithSeparator.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
    $repoRootWithSeparator += [System.IO.Path]::DirectorySeparatorChar
}

if (-not $logDirectory.StartsWith($repoRootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase) -and $logDirectory -ne $repoRoot) {
    throw "Security Exception: Invalid logDirectory path traversal detected. Path must be within the repository root."
}

if (-not (Test-Path -Path $logDirectory)) {
    New-Item -Path $logDirectory -ItemType Directory -Force | Out-Null
}

$runDate = Get-Date
$logPath = Join-Path -Path $logDirectory -ChildPath ("qoe-probe-{0}.log" -f $runDate.ToString('yyyy-MM-dd'))
$curlPath = Get-CurlExecutable -ScriptBasePath $scriptBasePath
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
$uploadMeasurementCache = @{}
$portableTools = $null
if (@($enabledTargets | Where-Object { (Get-TargetType -Target $_) -eq 'speedtest' }).Count -gt 0) {
    $portableTools = Get-PortableTools -ProbeRun $config.probeRun -ScriptBasePath $scriptBasePath
}

try {
    Write-Log -Message "Starting QoE probe using config $resolvedConfigPath" -LogPath $logPath

    $gcRepoRoot = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..'
    $gcTempDir = if ($null -ne $portableTools) { $portableTools.TemporaryDirectory } else { Join-Path -Path $gcRepoRoot -ChildPath 'bin\tmp' }
    $staleTemporaryArtifactCount = 0
    $staleTemporaryArtifactCount += Clean-TemporaryFiles -TemporaryDirectory $gcTempDir
    $staleTemporaryArtifactCount += Clean-OldLogs -RepoRoot $gcRepoRoot
    if ($staleTemporaryArtifactCount -gt 0) {
        Write-Log -Message ("Environment GC removed {0} stale artifact(s) or log(s)." -f $staleTemporaryArtifactCount) -LogPath $logPath
    }

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
        $targetType = Get-TargetType -Target $target
        try {
            if ($targetType -eq 'speedtest') {
                $speedTestResult = Invoke-SpeedTestTarget -Target $target -Config $config -PortableTools $portableTools -UploadMeasurementCache $uploadMeasurementCache
                if ($speedTestResult.Available) {
                    $successCount++
                }
                else {
                    $failureCount++
                }

                $timestampMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
                $lines.Add((Get-InfluxLine -Measurement $speedTestResult.Measurement -Tags $speedTestResult.Tags -Fields $speedTestResult.Fields -TimestampMs $timestampMs))
                $targetReports.Add($speedTestResult.Report) | Out-Null
                Write-Log -Message $speedTestResult.LogMessage -LogPath $logPath
            }
            else {
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
                    type = 'http'
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
        }
        catch {
            $failureCount++
            Write-Log -Message ("Target {0}/{1} failed: {2}" -f $target.service, $target.endpointName, $_.Exception.Message) -Level 'ERROR' -LogPath $logPath

            if ($targetType -eq 'speedtest') {
                $speedTestFailureResult = Get-SpeedTestFailureTargetResult -Target $target -Config $config -ErrorMessage ([string]$_.Exception.Message) -RunDurationMs ([double]((Get-Date) - $targetStart).TotalMilliseconds)
                $timestampMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
                $lines.Add((Get-InfluxLine -Measurement $speedTestFailureResult.Measurement -Tags $speedTestFailureResult.Tags -Fields $speedTestFailureResult.Fields -TimestampMs $timestampMs))
                $targetReports.Add($speedTestFailureResult.Report) | Out-Null
            }
            else {
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
                    type = 'http'
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

        try {
            Invoke-RestMethod -Uri $writeUri -Method Post -Headers @{ Authorization = "Token $tokenValue" } -Body $payload -ContentType 'text/plain; charset=utf-8' -TimeoutSec $influxWriteTimeoutSeconds | Out-Null
        }
        catch [System.Net.WebException] {
            $webEx = $_.Exception
            $response = $webEx.Response
            if ($null -ne $response) {
                $stream = $response.GetResponseStream()
                if ($null -ne $stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    $responseBody = $reader.ReadToEnd()
                    $reader.Close()
                    $stream.Close()
                    if (-not [string]::IsNullOrWhiteSpace($responseBody)) {
                        throw (New-Object System.Net.WebException("InfluxDB write failed. Response body: $responseBody", $webEx))
                    }
                }
            }
            throw
        }
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
        try {
            Invoke-RestMethod -Uri $writeUri -Method Post -Headers @{ Authorization = "Token $tokenValue" } -Body $probeOnlyPayload -ContentType 'text/plain; charset=utf-8' -TimeoutSec $influxWriteTimeoutSeconds | Out-Null
        }
        catch [System.Net.WebException] {
            $webEx = $_.Exception
            $response = $webEx.Response
            if ($null -ne $response) {
                $stream = $response.GetResponseStream()
                if ($null -ne $stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    $responseBody = $reader.ReadToEnd()
                    $reader.Close()
                    $stream.Close()
                    if (-not [string]::IsNullOrWhiteSpace($responseBody)) {
                        throw (New-Object System.Net.WebException("InfluxDB write failed. Response body: $responseBody", $webEx))
                    }
                }
            }
            throw
        }
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
            targets = $targetReports.ToArray()
        }

        Write-RunReport -Path $resolvedRunReportPath -Report $report
        Write-Log -Message ("Structured run report written to {0}" -f $resolvedRunReportPath) -LogPath $logPath
    }
}