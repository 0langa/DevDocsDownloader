using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class RunPage : Page
{
    private string? _lastJobId;

    public RunPage()
    {
        InitializeComponent();
    }

    private async void OnStartRun(object sender, RoutedEventArgs e)
    {
        try
        {
            var payload = new JsonObject
            {
                ["language"] = LanguageBox.Text,
                ["mode"] = ModeBox.SelectedItem?.ToString() ?? "important",
                ["source"] = string.IsNullOrWhiteSpace(SourceBox.Text) ? null : SourceBox.Text,
                ["validate_only"] = ValidateOnlyBox.IsChecked == true,
                ["force_refresh"] = ForceRefreshBox.IsChecked == true,
            };
            var result = await App.BackendHost.Client.StartRunLanguageAsync(payload);
            _lastJobId = result?["id"]?.GetValue<string>();
            JobStatusText.Text = JsonFormatter.Format(result);
            await RefreshEventsAsync();
        }
        catch (Exception exc)
        {
            JobStatusText.Text = exc.Message;
        }
    }

    private async void OnRefreshJob(object sender, RoutedEventArgs e)
    {
        await RefreshEventsAsync();
    }

    private async Task RefreshEventsAsync()
    {
        if (string.IsNullOrWhiteSpace(_lastJobId))
        {
            return;
        }
        var status = await App.BackendHost.Client.GetJobAsync(_lastJobId);
        var events = await App.BackendHost.Client.GetJobEventsAsync(_lastJobId);
        JobStatusText.Text = JsonFormatter.Format(status);
        EventsBox.Text = string.Join(Environment.NewLine + Environment.NewLine, events);
    }
}
