using System.Text;

namespace CXRadar.Bootstrapper;

internal sealed class BootstrapperForm : Form
{
    private readonly BootstrapperRunner _runner;
    private readonly TextBox _hubNameTextBox;
    private readonly TextBox _tokenTextBox;
    private readonly TextBox _speedTestPathTextBox;
    private readonly CheckBox _skipValidationCheckBox;
    private readonly CheckBox _runDryRunCheckBox;
    private readonly CheckBox _registerTasksCheckBox;
    private readonly Button _browseSpeedTestButton;
    private readonly Button _installButton;
    private readonly Button _closeButton;
    private readonly TextBox _statusTextBox;

    public BootstrapperForm(BootstrapperRunner runner)
    {
        _runner = runner;

        Text = "CX-Radar Bootstrapper";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(760, 560);
        Size = new Size(820, 620);

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(16),
            ColumnCount = 3,
            RowCount = 8
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 180));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        Controls.Add(layout);

        var titleLabel = new Label
        {
            AutoSize = true,
            Font = new Font(Font, FontStyle.Bold),
            Text = "Per-user CX-Radar bootstrap install"
        };
        layout.Controls.Add(titleLabel, 0, 0);
        layout.SetColumnSpan(titleLabel, 3);

        var introLabel = new Label
        {
            AutoSize = true,
            MaximumSize = new Size(740, 0),
            Text = "This EXE installs the CX-Radar runtime under LocalAppData, provisions config from the bootstrap templates, and optionally registers the scheduled tasks. Leave the token blank only if this PC already has the protected DPAPI token file."
        };
        layout.Controls.Add(introLabel, 0, 1);
        layout.SetColumnSpan(introLabel, 3);

        _hubNameTextBox = new TextBox { Dock = DockStyle.Fill };
        AddLabeledControl(layout, 2, "HUB name", _hubNameTextBox, null);

        _tokenTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            UseSystemPasswordChar = true
        };
        AddLabeledControl(layout, 3, "Influx token", _tokenTextBox, null);

        _speedTestPathTextBox = new TextBox { Dock = DockStyle.Fill };
        _browseSpeedTestButton = new Button
        {
            AutoSize = true,
            Text = "Browse..."
        };
        _browseSpeedTestButton.Click += BrowseSpeedTestButton_Click;
        AddLabeledControl(layout, 4, "speedtest.exe path", _speedTestPathTextBox, _browseSpeedTestButton);

        var optionsPanel = new FlowLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = true,
            Margin = new Padding(0)
        };

        _skipValidationCheckBox = new CheckBox
        {
            AutoSize = true,
            Text = "Skip validation"
        };
        optionsPanel.Controls.Add(_skipValidationCheckBox);

        _runDryRunCheckBox = new CheckBox
        {
            AutoSize = true,
            Text = "Run dry runs during install"
        };
        optionsPanel.Controls.Add(_runDryRunCheckBox);

        _registerTasksCheckBox = new CheckBox
        {
            AutoSize = true,
            Checked = true,
            Text = "Register scheduled tasks"
        };
        optionsPanel.Controls.Add(_registerTasksCheckBox);

        AddLabeledControl(layout, 5, "Options", optionsPanel, null);

        _statusTextBox = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            WordWrap = true
        };
        layout.Controls.Add(_statusTextBox, 0, 6);
        layout.SetColumnSpan(_statusTextBox, 3);

        var buttonPanel = new FlowLayoutPanel
        {
            AutoSize = true,
            Dock = DockStyle.Right,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            Margin = new Padding(0)
        };

        _installButton = new Button
        {
            AutoSize = true,
            Text = "Install"
        };
        _installButton.Click += InstallButton_Click;
        buttonPanel.Controls.Add(_installButton);

        _closeButton = new Button
        {
            AutoSize = true,
            Text = "Close"
        };
        _closeButton.Click += (_, _) => Close();
        buttonPanel.Controls.Add(_closeButton);

        layout.Controls.Add(buttonPanel, 0, 7);
        layout.SetColumnSpan(buttonPanel, 3);

        AppendStatus("Ready. The EXE will use bundled bootstrap-assets next to the executable.");
        var bundledSpeedTestPath = Path.Combine(AppContext.BaseDirectory, "bootstrap-assets", "tools", "ookla-speedtest", "speedtest.exe");
        if (File.Exists(bundledSpeedTestPath))
        {
            AppendStatus($"Bundled speedtest.exe detected at '{bundledSpeedTestPath}'.");
        }
        else
        {
            AppendStatus("No bundled speedtest.exe was found. The installer will fall back to the existing LocalAppData install or PATH unless you select a file manually.");
        }
    }

    private void BrowseSpeedTestButton_Click(object? sender, EventArgs e)
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Select speedtest.exe",
            Filter = "Executable files (*.exe)|*.exe|All files (*.*)|*.*",
            CheckFileExists = true,
            Multiselect = false
        };

        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            _speedTestPathTextBox.Text = dialog.FileName;
        }
    }

    private async void InstallButton_Click(object? sender, EventArgs e)
    {
        var hubName = _hubNameTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(hubName))
        {
            MessageBox.Show(this, "Enter the HUB name before starting the install.", "Missing HUB name", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            _hubNameTextBox.Focus();
            return;
        }

        var tokenText = _tokenTextBox.Text;
        if (string.IsNullOrWhiteSpace(tokenText) && !ProtectedTokenAlreadyExists())
        {
            MessageBox.Show(this, "This PC does not yet have the protected Influx token file. Paste the token or pre-provision it before running the EXE.", "Missing token", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            _tokenTextBox.Focus();
            return;
        }

        ToggleInputs(enabled: false);
        _statusTextBox.Clear();
        AppendStatus("Starting bootstrap install...");

        try
        {
            var options = new BootstrapperOptions(
                HubName: hubName,
                InfluxTokenPlainText: tokenText,
                SpeedTestCliSourcePath: _speedTestPathTextBox.Text.Trim(),
                SkipValidation: _skipValidationCheckBox.Checked,
                RunDryRun: _runDryRunCheckBox.Checked,
                RegisterScheduledTasks: _registerTasksCheckBox.Checked);

            var result = await _runner.RunAsync(options, CancellationToken.None);
            if (result.ExitCode != 0)
            {
                AppendStatus("Bootstrap install failed.");
                if (!string.IsNullOrWhiteSpace(result.StandardError))
                {
                    AppendStatus(result.StandardError.Trim());
                }
                else if (!string.IsNullOrWhiteSpace(result.StandardOutput))
                {
                    AppendStatus(result.StandardOutput.Trim());
                }

                MessageBox.Show(this, "The bootstrap install failed. Review the log output in this window.", "Install failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            var installResult = result.InstallResult;
            if (installResult is null)
            {
                AppendStatus("Bootstrap install completed, but the EXE did not receive a structured JSON result.");
                if (!string.IsNullOrWhiteSpace(result.StandardOutput))
                {
                    AppendStatus(result.StandardOutput.Trim());
                }
                MessageBox.Show(this, "The install completed without a structured result payload. Review the details in the log window.", "Install completed with warnings", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            AppendStatus("Bootstrap install completed successfully.");
            AppendStatus($"ProbeId: {installResult.ProbeId}");
            AppendStatus($"InstallRoot: {installResult.InstallRoot}");
            AppendStatus($"StatePath: {installResult.StatePath}");
            AppendStatus($"ProbeConfigPath: {installResult.ProbeConfigPath}");
            AppendStatus($"SpeedTestConfigPath: {installResult.SpeedTestConfigPath}");
            if (!string.IsNullOrWhiteSpace(installResult.SpeedTestCliPath))
            {
                AppendStatus($"SpeedTestCliPath: {installResult.SpeedTestCliPath}");
            }

            if (installResult.TaskOutputs.Length > 0)
            {
                AppendStatus("Scheduled task registration output:");
                foreach (var line in installResult.TaskOutputs)
                {
                    AppendStatus(line);
                }
            }

            MessageBox.Show(this, "CX-Radar was installed successfully for the current user.", "Install completed", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception exception)
        {
            AppendStatus("Bootstrap install failed with an exception.");
            AppendStatus(exception.Message);
            MessageBox.Show(this, exception.Message, "Install failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            ToggleInputs(enabled: true);
            _tokenTextBox.Clear();
        }
    }

    private bool ProtectedTokenAlreadyExists()
    {
        var credentialFilePath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CX-Radar", "secrets", "influxdb-token.credential.xml");
        return File.Exists(credentialFilePath);
    }

    private void ToggleInputs(bool enabled)
    {
        _hubNameTextBox.Enabled = enabled;
        _tokenTextBox.Enabled = enabled;
        _speedTestPathTextBox.Enabled = enabled;
        _skipValidationCheckBox.Enabled = enabled;
        _runDryRunCheckBox.Enabled = enabled;
        _registerTasksCheckBox.Enabled = enabled;
        _browseSpeedTestButton.Enabled = enabled;
        _installButton.Enabled = enabled;
        _closeButton.Enabled = enabled;
        UseWaitCursor = !enabled;
    }

    private void AppendStatus(string message)
    {
        var builder = new StringBuilder();
        builder.Append('[');
        builder.Append(DateTime.Now.ToString("HH:mm:ss"));
        builder.Append("] ");
        builder.Append(message);

        if (_statusTextBox.TextLength > 0)
        {
            _statusTextBox.AppendText(Environment.NewLine);
        }

        _statusTextBox.AppendText(builder.ToString());
    }

    private static void AddLabeledControl(TableLayoutPanel layout, int row, string labelText, Control mainControl, Control? sideControl)
    {
        var label = new Label
        {
            Anchor = AnchorStyles.Left,
            AutoSize = true,
            Text = labelText
        };
        layout.Controls.Add(label, 0, row);

        mainControl.Dock = DockStyle.Fill;
        layout.Controls.Add(mainControl, 1, row);

        if (sideControl is null)
        {
            var spacer = new Panel { Dock = DockStyle.Fill };
            layout.Controls.Add(spacer, 2, row);
        }
        else
        {
            sideControl.Anchor = AnchorStyles.Left;
            layout.Controls.Add(sideControl, 2, row);
        }
    }
}