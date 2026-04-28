[CmdletBinding()]
param(
    [Parameter()]
    [string]$TaskName = 'CX-Radar-QoE-Probe',

    [Parameter()]
    [string]$ScriptPath = '',

    [Parameter()]
    [string]$ConfigPath = '',

    [Parameter()]
    [ValidateRange(1, 1440)]
    [int]$IntervalMinutes = 5,

    [Parameter()]
    [ValidateSet('RemoteSigned', 'AllSigned', 'Bypass')]
    [string]$ExecutionPolicy = 'RemoteSigned',

    [Parameter()]
    [switch]$RunAsCurrentUser,

    [Parameter()]
    [string]$TaskDescription = 'Runs the CX-Radar QoE probe and sends metrics to InfluxDB Cloud.'
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

function Resolve-FullPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return [System.IO.Path]::GetFullPath((Resolve-Path -Path $Path).Path)
}

$scriptBasePath = Get-ScriptBasePath
if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
    $ScriptPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath 'qoe-probe.ps1'
}

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\config\probe-catalog.json'
}

$resolvedScriptPath = Resolve-FullPath -Path $ScriptPath
$resolvedConfigPath = Resolve-FullPath -Path $ConfigPath

if (-not (Test-Path -Path $resolvedScriptPath -PathType Leaf)) {
    throw "Probe script was not found at '$resolvedScriptPath'."
}

if (-not (Test-Path -Path $resolvedConfigPath -PathType Leaf)) {
    throw "Config file was not found at '$resolvedConfigPath'."
}

$powerShellPath = Join-Path -Path $PSHOME -ChildPath 'powershell.exe'
$actionArguments = @(
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy', $ExecutionPolicy,
    '-File', ('"{0}"' -f $resolvedScriptPath),
    '-ConfigPath', ('"{0}"' -f $resolvedConfigPath)
) -join ' '

$action = New-ScheduledTaskAction -Execute $powerShellPath -Argument $actionArguments
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RunOnlyIfNetworkAvailable -StartWhenAvailable

$currentUserName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if ($RunAsCurrentUser) {
    $principal = New-ScheduledTaskPrincipal -UserId $currentUserName -LogonType Interactive -RunLevel Limited
}
else {
    $principal = New-ScheduledTaskPrincipal -UserId $currentUserName -LogonType S4U -RunLevel Limited
}

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $TaskDescription
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force -ErrorAction Stop | Out-Null

Write-Output "Scheduled task '$TaskName' registered successfully with execution policy '$ExecutionPolicy'."