using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class SettingsPage : Page
{
    public SettingsPage()
    {
        InitializeComponent();
        HelpBox.Text = """
            DevDocsDownloader 1.0.1 desktop shell

            1. Start in Dashboard / Run for a single language or Bulk for multiple languages.
            2. Use Languages to discover available source catalog entries.
            3. Use Presets / Audit before large recurring runs.
            4. Use Reports, Output Browser, Checkpoints, and Cache to inspect results and recovery state.
            5. Cache policy and output settings are persisted through the backend settings file.
            """;
    }

    private async void OnLoadSettings(object sender, RoutedEventArgs e)
    {
        try
        {
            var settings = await App.BackendHost.Client.GetSettingsAsync();
            OutputDirBox.Text = settings?["output_dir"]?.GetValue<string>() ?? string.Empty;
            CachePolicyBox.SelectedItem = settings?["cache_policy"]?.GetValue<string>() ?? "use-if-present";
            CacheTtlBox.Text = settings?["cache_ttl_hours"]?.GetValue<int?>()?.ToString() ?? string.Empty;
        }
        catch (Exception exc)
        {
            HelpBox.Text = exc.Message;
        }
    }

    private async void OnSaveSettings(object sender, RoutedEventArgs e)
    {
        try
        {
            JsonNode? saved = await App.BackendHost.Client.SaveSettingsAsync(new JsonObject
            {
                ["output_dir"] = string.IsNullOrWhiteSpace(OutputDirBox.Text) ? null : OutputDirBox.Text,
                ["cache_policy"] = CachePolicyBox.SelectedItem?.ToString() ?? "use-if-present",
                ["cache_ttl_hours"] = int.TryParse(CacheTtlBox.Text, out var ttl) ? ttl : null,
            });
            HelpBox.Text = JsonFormatter.Format(saved);
        }
        catch (Exception exc)
        {
            HelpBox.Text = exc.Message;
        }
    }
}
