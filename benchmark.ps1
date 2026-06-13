$sw = [System.Diagnostics.Stopwatch]::StartNew()

# Setup test files
$tempDir = "test_temp_dir"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
for ($i = 0; $i -lt 1000; $i++) {
    New-Item -ItemType File -Path "$tempDir/file_$i.tmp" -Force | Out-Null
}

$removedCount = 0
$candidates = Get-ChildItem -Path $tempDir -Filter "*.tmp" -Force

$sw.Restart()
foreach ($candidate in $candidates) {
    $candidatePath = $candidate.FullName

    # Original logic
    if ([string]::IsNullOrWhiteSpace($candidatePath)) { continue }
    try {
        if (Test-Path -Path $candidatePath) {
            Remove-Item -Path $candidatePath -Recurse -Force
        }
    } catch {}

    if (-not (Test-Path -Path $candidatePath)) {
        $removedCount++
    }
}
$sw.Stop()
Write-Host "Baseline (Test-Path x2 + Remove-Item): $($sw.ElapsedMilliseconds) ms"

# Setup test files again
for ($i = 0; $i -lt 1000; $i++) {
    New-Item -ItemType File -Path "$tempDir/file_$i.tmp" -Force | Out-Null
}
$removedCount = 0
$candidates = Get-ChildItem -Path $tempDir -Filter "*.tmp" -Force

$sw.Restart()
foreach ($candidate in $candidates) {
    $candidatePath = $candidate.FullName

    # Optimized logic 1 (System.IO)
    try {
        Remove-Item -Path $candidatePath -Recurse -Force -ErrorAction Stop
        $removedCount++
    } catch {}
}
$sw.Stop()
Write-Host "Optimized 1 (Remove-Item Stop): $($sw.ElapsedMilliseconds) ms"

# Setup test files again
for ($i = 0; $i -lt 1000; $i++) {
    New-Item -ItemType File -Path "$tempDir/file_$i.tmp" -Force | Out-Null
}
$removedCount = 0
$candidates = Get-ChildItem -Path $tempDir -Filter "*.tmp" -Force

$sw.Restart()
foreach ($candidate in $candidates) {
    $candidatePath = $candidate.FullName

    # Optimized logic 2
    $exists = [System.IO.File]::Exists($candidatePath) -or [System.IO.Directory]::Exists($candidatePath)
    if ($exists) {
        try {
            [System.IO.File]::Delete($candidatePath)
            $removedCount++
        } catch {
            try {
                [System.IO.Directory]::Delete($candidatePath, $true)
                $removedCount++
            } catch {}
        }
    }
}
$sw.Stop()
Write-Host "Optimized 2 (System.IO.File::Delete): $($sw.ElapsedMilliseconds) ms"

Remove-Item -Path $tempDir -Recurse -Force
