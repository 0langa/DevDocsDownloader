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
            TrendText.Text = BuildTrendSummary(_latestReports["quality_trends"] as JsonObject, latestReport?["language"]?.GetValue<string>() ?? "");
            DiffText.Text = BuildDiffSummary(_latestReports["run_diffs"] as JsonObject, latestReport?["slug"]?.GetValue<string>() ?? "");
            LowestDocsText.Text = BuildLowestDocsSummary(latestReport?["validation"]?["document_results"] as JsonArray);
            HistoryList.ItemsSource = history?.Select(item => item?.GetValue<string>() ?? "").Where(item => !string.IsNullOrWhiteSpace(item)).ToList();
            BindCompareSelectors();
            PreviewTitleText.Text = "Latest run summary";
            ContentBox.Text = BuildLatestPreview(latestJson, latestReport);
        }
        catch (Exception exc)
        {
            SummaryText.Text = exc.Message;
        }
    }

    private void BindCompareSelectors()
    {
        if (_latestReports?["run_manifests"] is not JsonObject index || index.Count == 0)
        {
            CompareLanguageBox.ItemsSource = null;
            CompareCurrentBox.ItemsSource = null;
            ComparePreviousBox.ItemsSource = null;
            return;
        }
        var languages = index.Select(row => row.Key).OrderBy(x => x, StringComparer.OrdinalIgnoreCase).ToList();
        CompareLanguageBox.ItemsSource = languages;
        if (CompareLanguageBox.SelectedItem is null && languages.Count > 0)
        {
            CompareLanguageBox.SelectedItem = languages[0];
        }
        UpdateManifestSelectors();
    }

    private void OnCompareSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ReferenceEquals(sender, CompareLanguageBox))
        {
            UpdateManifestSelectors();
        }
    }

    private void UpdateManifestSelectors()
    {
        if (_latestReports?["run_manifests"] is not JsonObject index)
        {
            return;
        }
        var language = CompareLanguageBox.SelectedItem?.ToString() ?? "";
        if (string.IsNullOrWhiteSpace(language) || index[language] is not JsonArray manifests)
        {
            CompareCurrentBox.ItemsSource = null;
            ComparePreviousBox.ItemsSource = null;
            return;
        }
        var rows = manifests.Select(x => x?.GetValue<string>() ?? "").Where(x => !string.IsNullOrWhiteSpace(x)).ToList();
        CompareCurrentBox.ItemsSource = rows;
        ComparePreviousBox.ItemsSource = rows;
        if (rows.Count > 0)
        {
            CompareCurrentBox.SelectedItem ??= rows[0];
            ComparePreviousBox.SelectedItem ??= rows.Count > 1 ? rows[1] : rows[0];
        }
    }

    private async void OnCompareRuns(object sender, RoutedEventArgs e)
    {
        var language = CompareLanguageBox.SelectedItem?.ToString() ?? "";
        var current = CompareCurrentBox.SelectedItem?.ToString() ?? "";
        var previous = ComparePreviousBox.SelectedItem?.ToString() ?? "";
        if (string.IsNullOrWhiteSpace(language) || string.IsNullOrWhiteSpace(current) || string.IsNullOrWhiteSpace(previous))
        {
            DiffText.Text = "Compare runs: select language + both manifests.";
            return;
        }
        try
        {
            var payload = await App.BackendHost.Client.CompareRunsAsync(language, current, previous) as JsonObject;
            if (payload is null)
            {
                DiffText.Text = "Compare runs: no data.";
                return;
            }
            DiffText.Text = BuildDiffSummary(new JsonObject { [language] = payload }, language);
            var added = string.Join(", ", (payload["added"] as JsonArray)?.Select(x => x?.GetValue<string>() ?? "") ?? []);
            var removed = string.Join(", ", (payload["removed"] as JsonArray)?.Select(x => x?.GetValue<string>() ?? "") ?? []);
            var changed = string.Join(", ", (payload["changed"] as JsonArray)?.Select(x => x?.GetValue<string>() ?? "") ?? []);
            PreviewTitleText.Text = $"Run compare {language}";
            ContentBox.Text = $"Current: {current}\nPrevious: {previous}\n\nAdded:\n{added}\n\nRemoved:\n{removed}\n\nChanged:\n{changed}";
        }
        catch (Exception exc)
        {
            DiffText.Text = $"Compare runs failed: {exc.Message}";
        }
    }

    private static string BuildLowestDocsSummary(JsonArray? docs)
    {
        if (docs is null || docs.Count == 0)
        {
            return "Lowest-scoring docs: n/a";
        }
        var rows = docs
            .OfType<JsonObject>()
            .Select(row => new
            {
                Path = row["document_path"]?.GetValue<string>() ?? "",
                Score = row["quality_score"]?.GetValue<double?>() ?? 1.0,
                TopIssue = (row["issues"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault()?["message"]?.GetValue<string>() ?? "No issues",
            })
            .OrderBy(row => row.Score)
            .Take(3)
            .ToList();
        if (rows.Count == 0)
        {
            return "Lowest-scoring docs: n/a";
        }
        return "Lowest-scoring docs: " + string.Join(" | ", rows.Select(row => $"{row.Path} ({row.Score:0.00}) {row.TopIssue}"));
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

    private static string BuildTrendSummary(JsonObject? qualityTrends, string language)
    {
        if (qualityTrends is null || string.IsNullOrWhiteSpace(language))
        {
            return "Quality trend: n/a";
        }
        if (qualityTrends[language] is not JsonArray rows || rows.Count == 0)
        {
            return "Quality trend: n/a";
        }
        var scores = rows
            .OfType<JsonObject>()
            .Select(row => row["validation_score"]?.GetValue<double?>() ?? 0.0)
            .ToList();
        var spark = BuildSparkline(scores);
        var trend = "stable";
        if (scores.Count >= 2)
        {
            var delta = scores[^1] - scores[^2];
            trend = delta > 0.01 ? "improving" : delta < -0.01 ? "degrading" : "stable";
        }
        return $"Quality trend ({scores.Count} runs): {trend}  {spark}";
    }

    private static string BuildSparkline(IReadOnlyList<double> scores)
    {
        if (scores.Count == 0)
        {
            return "";
        }
        var levels = new[] { '▁', '▂', '▃', '▄', '▅', '▆', '▇', '█' };
        var min = scores.Min();
        var max = scores.Max();
        if (Math.Abs(max - min) < 0.0001)
        {
            return new string('▅', scores.Count);
        }
        return string.Concat(scores.Select(score =>
        {
            var normalized = (score - min) / (max - min);
            var idx = Math.Clamp((int)Math.Round(normalized * (levels.Length - 1)), 0, levels.Length - 1);
            return levels[idx];
        }));
    }

    private static string BuildDiffSummary(JsonObject? runDiffs, string languageSlug)
    {
        if (runDiffs is null || string.IsNullOrWhiteSpace(languageSlug) || runDiffs[languageSlug] is not JsonObject diff)
        {
            return "Run diff: n/a";
        }
        var summary = diff["summary"] as JsonObject;
        var added = summary?["added"]?.GetValue<int?>() ?? 0;
        var removed = summary?["removed"]?.GetValue<int?>() ?? 0;
        var changed = summary?["changed"]?.GetValue<int?>() ?? 0;
        return $"Compare runs: +{added} added, -{removed} removed, ~{changed} changed";
    }
}
