namespace CXRadar.Bootstrapper;

internal sealed record BootstrapperOptions(
    string HubName,
    string InfluxTokenPlainText,
    string SpeedTestCliSourcePath,
    bool SkipValidation,
    bool RunDryRun,
    bool RegisterScheduledTasks);

internal sealed class BootstrapperRunResult
{
    public required int ExitCode { get; init; }

    public required string StandardOutput { get; init; }

    public required string StandardError { get; init; }

    public BootstrapperInstallResult? InstallResult { get; init; }
}

internal sealed class BootstrapperInstallResult
{
    public string HubName { get; set; } = string.Empty;

    public string Site { get; set; } = string.Empty;

    public string ProbeId { get; set; } = string.Empty;

    public string InstallationId { get; set; } = string.Empty;

    public string InstallRoot { get; set; } = string.Empty;

    public string CurrentRoot { get; set; } = string.Empty;

    public string StatePath { get; set; } = string.Empty;

    public string ProbeConfigPath { get; set; } = string.Empty;

    public string SpeedTestConfigPath { get; set; } = string.Empty;

    public string InfluxCredentialFilePath { get; set; } = string.Empty;

    public string SpeedTestCliPath { get; set; } = string.Empty;

    public bool ValidationSkipped { get; set; }

    public bool DryRunSkipped { get; set; }

    public bool TaskRegistrationSkipped { get; set; }

    public string[] TaskOutputs { get; set; } = Array.Empty<string>();
}