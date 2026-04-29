using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class ReportsPage : Page
{
    private JsonObject? _latestReports;
    private bool _initialized;

    public ReportsPage()
    {
        InitializeComponent();
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (_initialized)
        {
            return;
        }
        _initialized = true;
        await RefreshAsync();
    }

    private async void OnRefresh(object sender, RoutedEventArgs e)
    {
        await RefreshAsync();
    }

    private async void OnHistorySelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (HistoryList.SelectedItem is not string path)
        {
            return;
        }
        try
        {
            var file = await App.BackendHost.Client.GetReportFileAsync(path);
            PreviewTitleText.Text = path;
            ContentBox.Text = file?["content"]?.GetValue<string>() ?? JsonFormatter.Format(file);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }

    private async Task RefreshAsync()
    {
        try
        {
            _latestReports = await App.BackendHost.Client.GetReportsAsync() as JsonObject;
            if (_latestReports is null)
            {
                SummaryText.Text = "No reports available.";
                return;
            }

            var latestJson = _latestReports["latest_json"] as JsonObject;
            var history = _latestReports["history_reports"] as JsonArray;
            var score = latestJson?["validation"]?["score"]?.GetValue<double?>();
            var issueCount = (latestJson?["validation"]?["issues"] as JsonArray)?.Count ?? 0;
            var warnings = (latestJson?["warnings"] as JsonArray)?.Count ?? 0;
            var failures = (latestJson?["failures"] as JsonArray)?.Count ?? 0;
            SummaryText.Text = $"Score: {(score.HasValue ? score.Value.ToString("0.00") : "n/a")}   Issues: {issueCount}   Warnings: {warnings}   Failures: {failures}";
            HistoryList.ItemsSource = history?.Select(item => item?.GetValue<string>() ?? "").Where(item => !string.IsNullOrWhiteSpace(item)).ToList();
            PreviewTitleText.Text = "Latest run summary";
            ContentBox.Text = JsonFormatter.Format(latestJson);
        }
        catch (Exception exc)
        {
            SummaryText.Text = exc.Message;
        }
    }
}
