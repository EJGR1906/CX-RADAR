using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace CXRadar.Bootstrapper;

internal sealed class BootstrapperRunner
{
    private const string BootstrapTokenEnvironmentVariable = "CX_RADAR_BOOTSTRAP_TOKEN";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public async Task<BootstrapperRunResult> RunAsync(BootstrapperOptions options, CancellationToken cancellationToken)
    {
        var assetsRoot = GetBootstrapAssetsRoot();
        var scriptPath = Path.Combine(assetsRoot, "installer", "bootstrap", "install-cx-radar-bootstrap.ps1");
        if (!File.Exists(scriptPath))
        {
            throw new FileNotFoundException("Bootstrap script was not found next to the EXE assets.", scriptPath);
        }

        var requestedSpeedTestPath = options.SpeedTestCliSourcePath;
        if (string.IsNullOrWhiteSpace(requestedSpeedTestPath))
        {
            var bundledSpeedTestPath = Path.Combine(assetsRoot, "tools", "ookla-speedtest", "speedtest.exe");
            if (File.Exists(bundledSpeedTestPath))
            {
                requestedSpeedTestPath = bundledSpeedTestPath;
            }
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = ResolvePowerShellExecutablePath(),
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = assetsRoot
        };

        startInfo.ArgumentList.Add("-NoProfile");
        startInfo.ArgumentList.Add("-NonInteractive");
        startInfo.ArgumentList.Add("-ExecutionPolicy");
        startInfo.ArgumentList.Add("RemoteSigned");
        startInfo.ArgumentList.Add("-EncodedCommand");
        startInfo.ArgumentList.Add(BuildEncodedBootstrapCommand(scriptPath, options, requestedSpeedTestPath));

        if (!string.IsNullOrWhiteSpace(options.InfluxTokenPlainText))
        {
            startInfo.Environment[BootstrapTokenEnvironmentVariable] = options.InfluxTokenPlainText;
        }

        using var process = new Process { StartInfo = startInfo };
        process.Start();

        var standardOutputTask = process.StandardOutput.ReadToEndAsync();
        var standardErrorTask = process.StandardError.ReadToEndAsync();

        await process.WaitForExitAsync(cancellationToken);

        var standardOutput = await standardOutputTask;
        var standardError = await standardErrorTask;

        BootstrapperInstallResult? installResult = null;
        if (process.ExitCode == 0 && !string.IsNullOrWhiteSpace(standardOutput))
        {
            installResult = JsonSerializer.Deserialize<BootstrapperInstallResult>(standardOutput, JsonOptions);
        }

        return new BootstrapperRunResult
        {
            ExitCode = process.ExitCode,
            StandardOutput = standardOutput,
            StandardError = standardError,
            InstallResult = installResult
        };
    }

    private static string GetBootstrapAssetsRoot()
    {
        var assetsRoot = Path.Combine(AppContext.BaseDirectory, "bootstrap-assets");
        if (!Directory.Exists(assetsRoot))
        {
            throw new DirectoryNotFoundException($"Bootstrap assets directory was not found at '{assetsRoot}'. Publish the EXE with the bundled bootstrap-assets folder.");
        }

        return assetsRoot;
    }

    private static string ResolvePowerShellExecutablePath()
    {
        var windowsPowerShell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        if (File.Exists(windowsPowerShell))
        {
            return windowsPowerShell;
        }

        return "powershell.exe";
    }

    private static string BuildEncodedBootstrapCommand(string scriptPath, BootstrapperOptions options, string requestedSpeedTestPath)
    {
        var lines = new List<string>
        {
            "$ErrorActionPreference = 'Stop'",
            "$params = @{",
            $"  HubName = '{EscapePowerShellString(options.HubName)}'",
            "  NonInteractive = $true"
        };

        if (options.SkipValidation)
        {
            lines.Add("  SkipValidation = $true");
        }

        if (!options.RunDryRun)
        {
            lines.Add("  SkipDryRun = $true");
        }

        if (!options.RegisterScheduledTasks)
        {
            lines.Add("  SkipTaskRegistration = $true");
        }

        if (!string.IsNullOrWhiteSpace(requestedSpeedTestPath))
        {
            lines.Add($"  SpeedTestCliSourcePath = '{EscapePowerShellString(requestedSpeedTestPath)}'");
        }

        lines.Add("}");
        lines.Add("if (-not [string]::IsNullOrWhiteSpace($env:CX_RADAR_BOOTSTRAP_TOKEN)) {");
        lines.Add("  $params['InfluxToken'] = ConvertTo-SecureString $env:CX_RADAR_BOOTSTRAP_TOKEN -AsPlainText -Force");
        lines.Add("}");
        lines.Add($"& '{EscapePowerShellString(scriptPath)}' @params | ConvertTo-Json -Depth 8");

        var script = string.Join(Environment.NewLine, lines);
        return Convert.ToBase64String(Encoding.Unicode.GetBytes(script));
    }

    private static string EscapePowerShellString(string value)
    {
        return value.Replace("'", "''");
    }
}