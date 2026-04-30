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
            var latestReport = (latestJson?["reports"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault();
            var history = _latestReports["history_reports"] as JsonArray;
            var score = latestReport?["validation"]?["score"]?.GetValue<double?>();
            var issueCount = (latestReport?["validation"]?["issues"] as JsonArray)?.Count ?? 0;
            var warnings = (latestReport?["warnings"] as JsonArray)?.Count ?? 0;
            var failures = (latestReport?["failures"] as JsonArray)?.Count ?? 0;
            SummaryText.Text = $"Score: {(score.HasValue ? score.Value.ToString("0.00") : "n/a")}   Issues: {issueCount}   Warnings: {warnings}   Failures: {failures}";
            HistoryList.ItemsSource = history?.Select(item => item?.GetValue<string>() ?? "").Where(item => !string.IsNullOrWhiteSpace(item)).ToList();
            PreviewTitleText.Text = "Latest run summary";
            ContentBox.Text = BuildLatestPreview(latestJson, latestReport);
        }
        catch (Exception exc)
        {
            SummaryText.Text = exc.Message;
        }
    }

    private static string BuildLatestPreview(JsonObject? latestJson, JsonObject? latestReport)
    {
        if (latestJson is null)
        {
            return "No latest report available.";
        }

        var lines = new List<string> { "Latest report", "" };
        if (latestReport is not null)
        {
            var language = latestReport["language"]?.GetValue<string>() ?? "";
            var source = latestReport["source"]?.GetValue<string>() ?? "";
            if (!string.IsNullOrWhiteSpace(language))
            {
                lines.Add($"{language} ({source})");
                lines.Add("");
            }
        }
        var validation = latestReport?["validation"] as JsonObject;
        var issues = validation?["issues"] as JsonArray;
        if (issues is not null && issues.Count > 0)
        {
            lines.Add("Validation issues");
            foreach (var node in issues.OfType<JsonObject>())
            {
                var level = node["level"]?.GetValue<string>() ?? "info";
                var code = node["code"]?.GetValue<string>() ?? "issue";
                var message = node["message"]?.GetValue<string>() ?? "";
                var suggestion = node["suggestion"]?.GetValue<string>() ?? "";
                lines.Add($"- [{level}] {code}: {message}");
                if (!string.IsNullOrWhiteSpace(suggestion))
                {
                    lines.Add($"  Suggestion: {suggestion}");
                }
            }
            lines.Add("");
        }

        var failures = latestReport?["failures"] as JsonArray;
        if (failures is not null && failures.Count > 0)
        {
            lines.Add("Failures");
            foreach (var node in failures.OfType<JsonObject>())
            {
                var code = node["code"]?.GetValue<string>() ?? "failure";
                var message = node["message"]?.GetValue<string>() ?? "";
                var hint = node["hint"]?.GetValue<string>() ?? "";
                lines.Add($"- [{code}] {message}");
                if (!string.IsNullOrWhiteSpace(hint))
                {
                    lines.Add($"  Hint: {hint}");
                }
            }
            lines.Add("");
        }

        lines.Add("Raw JSON");
        lines.Add(JsonFormatter.Format(latestJson));
        return string.Join(Environment.NewLine, lines);
    }
}
