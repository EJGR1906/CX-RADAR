[CmdletBinding()]
param(
    [Parameter()]
    [string]$BinRoot = '',

    [Parameter()]
    [string]$NodeZipUrl = 'https://nodejs.org/dist/latest-v20.x/node-v20.20.2-win-x64.zip',

    [Parameter()]
    [string]$YtDlpUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe',

    [Parameter()]
    [string]$FastCliVersion = '5.2.0',

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

function Invoke-FileDownload {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [Parameter(Mandatory = $true)]
        [string]$OutputPath
    )

    $parameters = @{
        Uri = $Uri
        OutFile = $OutputPath
    }

    if ((Get-Command -Name 'Invoke-WebRequest').Parameters.ContainsKey('UseBasicParsing')) {
        $parameters.UseBasicParsing = $true
    }

    Invoke-WebRequest @parameters | Out-Null
}

function Expand-ArchiveFlat {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ZipPath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    $stagingPath = Join-Path -Path (Split-Path -Path $ZipPath -Parent) -ChildPath (([System.IO.Path]::GetFileNameWithoutExtension($ZipPath)) + '-extract')
    if (Test-Path -Path $stagingPath -PathType Container) {
        Remove-Item -Path $stagingPath -Recurse -Force
    }

    Expand-Archive -Path $ZipPath -DestinationPath $stagingPath -Force

    $nodeExecutable = Get-ChildItem -Path $stagingPath -Recurse -Filter 'node.exe' | Select-Object -First 1
    if ($null -eq $nodeExecutable) {
        throw "The extracted archive '$ZipPath' does not contain node.exe."
    }

    $sourceRoot = Split-Path -Path $nodeExecutable.FullName -Parent
    if (Test-Path -Path $DestinationPath -PathType Container) {
        Remove-Item -Path $DestinationPath -Recurse -Force
    }

    New-DirectoryIfMissing -Path $DestinationPath
    foreach ($item in (Get-ChildItem -Path $sourceRoot -Force)) {
        Copy-Item -Path $item.FullName -Destination $DestinationPath -Recurse -Force
    }

    Remove-Item -Path $stagingPath -Recurse -Force
}

function Test-PortableNodeRuntime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodeRoot
    )

    $requiredPaths = @(
        (Join-Path -Path $NodeRoot -ChildPath 'node.exe'),
        (Join-Path -Path $NodeRoot -ChildPath 'npm.cmd'),
        (Join-Path -Path $NodeRoot -ChildPath 'node_modules\npm\bin\npm-cli.js'),
        (Join-Path -Path $NodeRoot -ChildPath 'node_modules\npm\bin\npm-prefix.js')
    )

    foreach ($requiredPath in $requiredPaths) {
        if (-not (Test-Path -Path $requiredPath -PathType Leaf)) {
            return $false
        }
    }

    return $true
}

function Get-FastCliScriptPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FastCliRoot
    )

    return (Join-Path -Path $FastCliRoot -ChildPath 'node_modules\fast-cli\distribution\cli.js')
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


function Test-FastCliInstallation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodeRoot,

        [Parameter(Mandatory = $true)]
        [string]$FastCliRoot
    )

    $nodeExePath = Join-Path -Path $NodeRoot -ChildPath 'node.exe'
    $fastCliScriptPath = Get-FastCliScriptPath -FastCliRoot $FastCliRoot

    if (-not (Test-Path -Path $nodeExePath -PathType Leaf) -or -not (Test-Path -Path $fastCliScriptPath -PathType Leaf)) {
        return $false
    }

    $processStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processStartInfo.FileName = $nodeExePath
    $processStartInfo.Arguments = ('"{0}" --version' -f ($fastCliScriptPath.Replace('"', '\"')))
    $processStartInfo.WorkingDirectory = $FastCliRoot
    $processStartInfo.UseShellExecute = $false
    $processStartInfo.RedirectStandardOutput = $true
    $processStartInfo.RedirectStandardError = $true
    $processStartInfo.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $processStartInfo

    $null = $process.Start()
    $process.WaitForExit()
    $null = $process.StandardOutput.ReadToEnd()
    $null = $process.StandardError.ReadToEnd()

    return ($process.ExitCode -eq 0)
}

function Install-FastCli {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NodeRoot,

        [Parameter(Mandatory = $true)]
        [string]$FastCliRoot,

        [Parameter(Mandatory = $true)]
        [string]$FastCliVersion,

        [Parameter(Mandatory = $true)]
        [string]$PuppeteerCacheDir,

        [Parameter(Mandatory = $true)]
        [string]$NpmCacheDir,

        [Parameter(Mandatory = $true)]
        [string]$TemporaryDirectory
    )

    $npmCommandPath = Join-Path -Path $NodeRoot -ChildPath 'npm.cmd'
    if (-not (Test-Path -Path $npmCommandPath -PathType Leaf)) {
        throw "Portable npm was not found at '$npmCommandPath'."
    }

    New-DirectoryIfMissing -Path $PuppeteerCacheDir
    New-DirectoryIfMissing -Path $NpmCacheDir
    New-DirectoryIfMissing -Path $TemporaryDirectory
    New-DirectoryIfMissing -Path $FastCliRoot

    $previousPuppeteerCacheDir = $env:PUPPETEER_CACHE_DIR
    $previousPuppeteerTmpDir = $env:PUPPETEER_TMP_DIR
    $previousNpmCacheDir = $env:npm_config_cache
    $previousPath = $env:PATH
    $lastExitCode = 0

    for ($attempt = 1; $attempt -le 2; $attempt++) {
        if (Test-Path -Path $FastCliRoot -PathType Container) {
            Remove-Item -Path $FastCliRoot -Recurse -Force
        }

        New-DirectoryIfMissing -Path $FastCliRoot

        try {
            $env:PUPPETEER_CACHE_DIR = $PuppeteerCacheDir
            $env:PUPPETEER_TMP_DIR = $TemporaryDirectory
            $env:npm_config_cache = $NpmCacheDir
            $env:PATH = '{0};{1}' -f $NodeRoot, $previousPath

            & $npmCommandPath install --prefix $FastCliRoot --no-fund --no-audit ("fast-cli@{0}" -f $FastCliVersion) | Out-Null
            $lastExitCode = $LASTEXITCODE
        }
        finally {
            $env:PUPPETEER_CACHE_DIR = $previousPuppeteerCacheDir
            $env:PUPPETEER_TMP_DIR = $previousPuppeteerTmpDir
            $env:npm_config_cache = $previousNpmCacheDir
            $env:PATH = $previousPath
        }

        $fastCliScript = Get-FastCliScriptPath -FastCliRoot $FastCliRoot
        if (Test-Path -Path $fastCliScript -PathType Leaf) {
            Patch-FastCliTimeout -FastCliScriptPath $fastCliScript
            if (Test-FastCliInstallation -NodeRoot $NodeRoot -FastCliRoot $FastCliRoot) {
                return $fastCliScript
            }
        }
    }

    if ($lastExitCode -ne 0) {
        throw "npm install fast-cli@$FastCliVersion failed with exit code $lastExitCode."
    }

    throw "fast-cli entrypoint at '$fastCliScript' did not pass a post-install validation run."
}

$scriptBasePath = Get-ScriptBasePath
if ([string]::IsNullOrWhiteSpace($BinRoot)) {
    $BinRoot = Get-FullPathFromBase -BasePath $scriptBasePath -ChildPath '..\bin'
}

$resolvedBinRoot = [System.IO.Path]::GetFullPath($BinRoot)
$downloadsDirectory = Join-Path -Path $resolvedBinRoot -ChildPath '_downloads'
$nodeRoot = Join-Path -Path $resolvedBinRoot -ChildPath 'node'
$fastCliRoot = Join-Path -Path $resolvedBinRoot -ChildPath 'fast-cli'
$ytDlpPath = Join-Path -Path $resolvedBinRoot -ChildPath 'yt-dlp.exe'
$puppeteerCacheDir = Join-Path -Path $resolvedBinRoot -ChildPath 'puppeteer-cache'
$temporaryDirectory = Join-Path -Path $resolvedBinRoot -ChildPath 'tmp'
$npmCacheDirectory = Join-Path -Path $resolvedBinRoot -ChildPath 'npm-cache'

New-DirectoryIfMissing -Path $resolvedBinRoot
New-DirectoryIfMissing -Path $downloadsDirectory

$nodeZipFileName = [System.IO.Path]::GetFileName(([System.Uri]$NodeZipUrl).AbsolutePath)
$nodeZipPath = Join-Path -Path $downloadsDirectory -ChildPath $nodeZipFileName

if ($Force -or -not (Test-PortableNodeRuntime -NodeRoot $nodeRoot)) {
    if (-not (Test-Path -Path $nodeZipPath -PathType Leaf)) {
        Invoke-FileDownload -Uri $NodeZipUrl -OutputPath $nodeZipPath
    }
    Expand-ArchiveFlat -ZipPath $nodeZipPath -DestinationPath $nodeRoot
}

if (Test-Path -Path $nodeZipPath -PathType Leaf) {
    Remove-Item -Path $nodeZipPath -Force -ErrorAction SilentlyContinue
}

if ($Force -or -not (Test-Path -Path $ytDlpPath -PathType Leaf)) {
    Invoke-FileDownload -Uri $YtDlpUrl -OutputPath $ytDlpPath
}

$fastCliScript = Get-FastCliScriptPath -FastCliRoot $fastCliRoot
if ($Force -and (Test-Path -Path $fastCliRoot -PathType Container)) {
    Remove-Item -Path $fastCliRoot -Recurse -Force
}

if ($Force -or -not (Test-FastCliInstallation -NodeRoot $nodeRoot -FastCliRoot $fastCliRoot)) {
    $fastCliScript = Install-FastCli -NodeRoot $nodeRoot -FastCliRoot $fastCliRoot -FastCliVersion $FastCliVersion -PuppeteerCacheDir $puppeteerCacheDir -NpmCacheDir $npmCacheDirectory -TemporaryDirectory $temporaryDirectory
}

Patch-FastCliTimeout -FastCliScriptPath $fastCliScript

[pscustomobject]@{
    BinRoot = [string]$resolvedBinRoot
    NodeExe = [string](Join-Path -Path $nodeRoot -ChildPath 'node.exe')
    NpmCmd = [string](Join-Path -Path $nodeRoot -ChildPath 'npm.cmd')
    FastCliRoot = [string]$fastCliRoot
    FastCliScript = [string]$fastCliScript
    YtDlpExe = [string]$ytDlpPath
    PuppeteerCacheDir = [string]$puppeteerCacheDir
    TemporaryDirectory = [string]$temporaryDirectory
}