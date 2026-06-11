$configPath = Resolve-Path ".\config\probe-catalog.json"
$config = Get-Content -Path $configPath -Raw | ConvertFrom-Json

$baseUrl = $config.influx.baseUrl

# Get Token
$credPath = [Environment]::ExpandEnvironmentVariables($config.influx.credentialFilePath)
if (Test-Path $credPath) {
    $importedSecret = Import-Clixml -Path $credPath
    if ($importedSecret -is [System.Management.Automation.PSCredential]) {
        $token = $importedSecret.GetNetworkCredential().Password
    } elseif ($importedSecret -is [securestring]) {
        $credential = New-Object System.Management.Automation.PSCredential('token', $importedSecret)
        $token = $credential.GetNetworkCredential().Password
    }
}

$headers = @{
    Authorization = "Token $token"
    "Content-Type" = "application/json"
}

Write-Output "Querying organizations..."
try {
    $orgs = Invoke-RestMethod -Uri "$baseUrl/api/v2/orgs" -Headers $headers -Method Get
    $orgs.orgs | Format-Table id, name, description
} catch {
    Write-Warning "Failed orgs query: $_"
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        Write-Warning "Response body: $($reader.ReadToEnd())"
    }
}

Write-Output "Querying buckets..."
try {
    $buckets = Invoke-RestMethod -Uri "$baseUrl/api/v2/buckets" -Headers $headers -Method Get
    $buckets.buckets | Format-Table id, name, orgID, retentionRules
} catch {
    Write-Warning "Failed buckets query: $_"
}
