$configPath = Resolve-Path ".\config\probe-catalog.json"
$config = Get-Content -Path $configPath -Raw | ConvertFrom-Json

$credPath = [Environment]::ExpandEnvironmentVariables($config.influx.credentialFilePath)
Write-Output "Credential path: $credPath"
Write-Output "File exists: $(Test-Path $credPath)"

if (Test-Path $credPath) {
    $importedSecret = Import-Clixml -Path $credPath
    if ($importedSecret -is [System.Management.Automation.PSCredential]) {
        $token = $importedSecret.GetNetworkCredential().Password
        Write-Output "Secret is PSCredential"
    } elseif ($importedSecret -is [securestring]) {
        $credential = New-Object System.Management.Automation.PSCredential('token', $importedSecret)
        $token = $credential.GetNetworkCredential().Password
        Write-Output "Secret is SecureString"
    } else {
        Write-Output "Secret is unknown type: $($importedSecret.GetType().FullName)"
        $token = $importedSecret.ToString()
    }
} else {
    Write-Output "No credential file found, checking env vars"
    $token = [Environment]::GetEnvironmentVariable($config.influx.tokenEnvVar, 'Process')
    if ([string]::IsNullOrWhiteSpace($token)) {
        $token = [Environment]::GetEnvironmentVariable($config.influx.tokenEnvVar, 'User')
    }
}

if ($token) {
    Write-Output "Token Length: $($token.Length)"
    Write-Output "Token Starts with: $($token.Substring(0, [Math]::Min(5, $token.Length)))..."
} else {
    Write-Output "Token is empty"
}
