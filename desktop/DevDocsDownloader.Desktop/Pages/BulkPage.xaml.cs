using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class BulkPage : Page
{
    private string? _lastJobId;

    public BulkPage()
    {
        InitializeComponent();
    }

    private async void OnStartBulk(object sender, RoutedEventArgs e)
    {
        try
        {
            var languages = LanguagesBox.Text.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            var payload = new JsonObject
            {
                ["languages"] = new JsonArray(languages.Select(item => JsonValue.Create(item)).ToArray()),
                ["mode"] = ModeBox.SelectedItem?.ToString() ?? "important",
                ["language_concurrency"] = int.TryParse(ConcurrencyBox.Text, out var concurrency) ? concurrency : 3,
                ["concurrency_policy"] = PolicyBox.SelectedItem?.ToString() ?? "static",
            };
            var result = await App.BackendHost.Client.StartBulkAsync(payload);
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
