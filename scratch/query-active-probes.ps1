# Query InfluxDB for active probes and their tags
$ErrorActionPreference = 'Stop'

$configPath = Resolve-Path ".\config\probe-catalog.json"
$config = Get-Content -Path $configPath -Raw | ConvertFrom-Json

$baseUrl = $config.influx.baseUrl
$org = $config.influx.org
$bucket = $config.influx.bucket

# Get Token
$credPath = [Environment]::ExpandEnvironmentVariables($config.influx.credentialFilePath)
if (-not (Test-Path $credPath)) {
    # Try process/user env var
    $token = [Environment]::GetEnvironmentVariable($config.influx.tokenEnvVar, 'Process')
    if ([string]::IsNullOrWhiteSpace($token)) {
        $token = [Environment]::GetEnvironmentVariable($config.influx.tokenEnvVar, 'User')
    }
} else {
    $importedSecret = Import-Clixml -Path $credPath
    if ($importedSecret -is [System.Management.Automation.PSCredential]) {
        $token = $importedSecret.GetNetworkCredential().Password
    } elseif ($importedSecret -is [securestring]) {
        $credential = New-Object System.Management.Automation.PSCredential('token', $importedSecret)
        $token = $credential.GetNetworkCredential().Password
    }
}

if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Error "Could not find InfluxDB token."
}

$fluxQuery = @"
from(bucket: "$bucket")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> group(columns: ["probe_id", "site"])
  |> last()
  |> keep(columns: ["probe_id", "site", "_time"])
"@

$body = @{
    query = $fluxQuery
    type = "flux"
} | ConvertTo-Json

$headers = @{
    Authorization = "Token $token"
    "Content-Type" = "application/json"
    Accept = "application/csv"
}

$response = Invoke-RestMethod -Uri "$baseUrl/api/v2/query?org=$org" -Method Post -Headers $headers -Body $body
$response
