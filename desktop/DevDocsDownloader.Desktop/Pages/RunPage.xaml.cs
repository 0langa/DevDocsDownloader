using System.ComponentModel;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class RunPage : Page
{
    private sealed class CatalogEntry
    {
        public required string Language { get; init; }
        public required string Source { get; init; }
        public required string Slug { get; init; }
        public string Version { get; init; } = "latest";

        public string DisplayText => Version == "latest"
            ? $"{Language} ({Source})"
            : $"{Language} {Version} ({Source})";

        public override string ToString() => DisplayText;
    }

    private static readonly string[] FallbackSources = ["Any (auto)", "dash", "devdocs", "mdn"];

    private readonly List<CatalogEntry> _catalog = [];
    private bool _initialized;
    private CatalogEntry? _selectedLanguage;

    public RunPage()
    {
        InitializeComponent();
        App.MainViewModel.PropertyChanged += OnShellPropertyChanged;
        EventsList.ItemsSource = App.MainViewModel.ActivityLines;
        SourceBox.ItemsSource = FallbackSources;
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (!_initialized)
        {
            _initialized = true;
            LanguageBox.Text = "";
            PopulateSourceBox();
            ModeBox.SelectedItem = App.MainViewModel.DefaultMode;
            ValidateOnlyBox.IsChecked = false;
            ForceRefreshBox.IsChecked = false;
            OutputRootText.Text = $"Output root: {App.MainViewModel.CurrentOutputRoot}";
            RefreshProgress();
            ValidateForm();
            await LoadCatalogAsync();
            return;
        }

        OutputRootText.Text = $"Output root: {App.MainViewModel.CurrentOutputRoot}";
        RefreshProgress();
    }

    public void ApplySuggestedLanguage(string language, string source)
    {
        var entry = FindBestMatch(language, source);
        _selectedLanguage = entry;
        LanguageBox.Text = entry?.Language ?? language;
        if (!string.IsNullOrWhiteSpace(source))
        {
            SetSourceSelection(source);
        }
        ValidateForm();
    }

    private async Task LoadCatalogAsync()
    {
        try
        {
            var result = await App.BackendHost.Client.GetLanguagesAsync();
            _catalog.Clear();
            foreach (var item in result ?? [])
            {
                if (item is not JsonObject row)
                {
                    continue;
                }
                var language = row["language"]?.GetValue<string>() ?? "";
                var source = row["source"]?.GetValue<string>() ?? "";
                var slug = row["slug"]?.GetValue<string>() ?? "";
                var version = row["version"]?.GetValue<string>() ?? "";
                if (string.IsNullOrWhiteSpace(language) || string.IsNullOrWhiteSpace(source))
                {
                    continue;
                }
                _catalog.Add(new CatalogEntry
                {
                    Language = language,
                    Source = source,
                    Slug = slug,
                    Version = string.IsNullOrWhiteSpace(version) ? "latest" : version,
                });
            }

            PopulateSourceBox();
            if (_selectedLanguage is not null)
            {
                SetSourceSelection(_selectedLanguage.Source);
            }
            ValidateForm();
        }
        catch
        {
            PopulateSourceBox();
        }
    }

    private async void OnStartRun(object sender, RoutedEventArgs e)
    {
        try
        {
            var source = GetSelectedSource();
            var payload = BuildRunPayload(source, dryRun: false);
            var result = await App.BackendHost.Client.StartRunLanguageAsync(payload);
            var jobId = result?["id"]?.GetValue<string>() ?? "";
            var language = payload["language"]?.GetValue<string>() ?? "language";
            var status = result?["status"]?.GetValue<string>() ?? "running";
            var queuePosition = result?["queue_position"]?.GetValue<int?>();
            App.MainViewModel.DefaultMode = payload["mode"]?.GetValue<string>() ?? App.MainViewModel.DefaultMode;
            App.MainViewModel.SourcePreference = source ?? "";
            await App.MainViewModel.StartTrackingJobAsync(jobId, language, "run_language", status, queuePosition);
            RefreshProgress();
        }
        catch (Exception exc)
        {
            ActivityText.Text = exc.Message;
        }
    }

    private async void OnPreview(object sender, RoutedEventArgs e)
    {
        try
        {
            var source = GetSelectedSource();
            var payload = BuildRunPayload(source, dryRun: true);
            var result = await App.BackendHost.Client.StartRunLanguageAsync(payload);
            var jobId = result?["id"]?.GetValue<string>() ?? "";
            var language = payload["language"]?.GetValue<string>() ?? "language";
            var status = result?["status"]?.GetValue<string>() ?? "running";
            var queuePosition = result?["queue_position"]?.GetValue<int?>();

            await App.MainViewModel.StartTrackingJobAsync(jobId, $"Preview {language}", "run_language", status, queuePosition);
            var summary = await WaitForJobSummaryAsync(jobId);
            if (summary is not null)
            {
                await ShowPreviewDialogAsync(summary);
            }
            RefreshProgress();
        }
        catch (Exception exc)
        {
            ActivityText.Text = exc.Message;
        }
    }

    private async void OnCancelJob(object sender, RoutedEventArgs e)
    {
        await App.MainViewModel.CancelActiveJobAsync();
    }

    private void OnFormChanged(object sender, object e)
    {
        ValidateForm();
    }

    private void OnLanguageTextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput)
        {
            return;
        }

        _selectedLanguage = null;
        var query = sender.Text.Trim();
        if (string.IsNullOrWhiteSpace(query))
        {
            sender.ItemsSource = null;
            ValidateForm();
            return;
        }

        sender.ItemsSource = _catalog
            .Where(item => item.Language.Contains(query, StringComparison.OrdinalIgnoreCase)
                || item.Slug.Contains(query, StringComparison.OrdinalIgnoreCase)
                || item.Source.Contains(query, StringComparison.OrdinalIgnoreCase)
                || item.Version.Contains(query, StringComparison.OrdinalIgnoreCase))
            .OrderBy(item => item.Language, StringComparer.OrdinalIgnoreCase)
            .ThenBy(item => item.Source, StringComparer.OrdinalIgnoreCase)
            .ThenByDescending(item => item.Version, StringComparer.OrdinalIgnoreCase)
            .Take(30)
            .ToList();
        ValidateForm();
    }

    private void OnLanguageSuggestionChosen(AutoSuggestBox sender, AutoSuggestBoxSuggestionChosenEventArgs args)
    {
        if (args.SelectedItem is not CatalogEntry entry)
        {
            return;
        }

        ApplyLanguageEntry(entry);
    }

    private void OnLanguageQuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        if (args.ChosenSuggestion is CatalogEntry chosen)
        {
            ApplyLanguageEntry(chosen);
            return;
        }

        var query = (args.QueryText ?? "").Trim();
        if (string.IsNullOrWhiteSpace(query))
        {
            sender.ItemsSource = null;
            ValidateForm();
            return;
        }

        var match = FindBestMatch(query, GetSelectedSource());
        if (match is not null)
        {
            ApplyLanguageEntry(match);
            return;
        }

        _selectedLanguage = null;
        sender.Text = query;
        sender.ItemsSource = null;
        ValidateForm();
    }

    private void ApplyLanguageEntry(CatalogEntry entry)
    {
        _selectedLanguage = entry;
        LanguageBox.Text = entry.Language;
        LanguageBox.ItemsSource = null;
        SetSourceSelection(entry.Source);
        ValidateForm();
    }

    private void OnShellPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (DispatcherQueue.HasThreadAccess)
        {
            RefreshProgress();
            return;
        }
        DispatcherQueue.TryEnqueue(RefreshProgress);
    }

    private void RefreshProgress()
    {
        OutputRootText.Text = $"Output root: {App.MainViewModel.CurrentOutputRoot}";
        if (ModeBox.SelectedItem is null)
        {
            ModeBox.SelectedItem = App.MainViewModel.DefaultMode;
        }
        ProgressBar.Visibility = App.MainViewModel.ProgressVisible ? Visibility.Visible : Visibility.Collapsed;
        ProgressBar.IsIndeterminate = App.MainViewModel.ProgressIndeterminate;
        ProgressBar.Value = App.MainViewModel.ProgressValue;
        PhaseText.Text = string.IsNullOrWhiteSpace(App.MainViewModel.ProgressPhase)
            ? "Idle"
            : $"Phase: {App.MainViewModel.ProgressPhase}";
        ActivityText.Text = string.IsNullOrWhiteSpace(App.MainViewModel.LatestActivity)
            ? "No active work."
            : App.MainViewModel.LatestActivity;
        CountsText.Text = App.MainViewModel.TotalDocuments > 0
            ? $"{App.MainViewModel.CompletedDocuments} / {App.MainViewModel.TotalDocuments} documents formatted"
            : App.MainViewModel.CompletedDocuments > 0
                ? $"{App.MainViewModel.CompletedDocuments} documents formatted"
                : "";
        WarningsText.Text = App.MainViewModel.WarningCount > 0 || App.MainViewModel.FailureCount > 0
            ? $"Warnings: {App.MainViewModel.WarningCount}   Failures: {App.MainViewModel.FailureCount}"
            : "";
    }

    private void PopulateSourceBox()
    {
        var current = GetSelectedSource() ?? App.MainViewModel.SourcePreference;
        var sources = _catalog
            .Select(item => item.Source)
            .Where(item => !string.IsNullOrWhiteSpace(item))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(item => item, StringComparer.OrdinalIgnoreCase)
            .ToList();
        sources.Insert(0, "Any (auto)");
        if (sources.Count == 1)
        {
            sources = [..FallbackSources];
        }

        SourceBox.ItemsSource = sources;
        SetSourceSelection(current);
    }

    private void SetSourceSelection(string? source)
    {
        var items = (SourceBox.ItemsSource as IEnumerable<string>) ?? FallbackSources;
        var selected = items.FirstOrDefault(item => item.Equals(source, StringComparison.OrdinalIgnoreCase));
        SourceBox.SelectedItem = selected ?? items.FirstOrDefault();
    }

    private string? GetSelectedSource()
    {
        var selected = SourceBox.SelectedItem?.ToString();
        return selected == "Any (auto)" || string.IsNullOrWhiteSpace(selected) ? null : selected;
    }

    private CatalogEntry? FindBestMatch(string value, string? preferredSource = null)
    {
        var query = value.Trim();
        if (string.IsNullOrWhiteSpace(query))
        {
            return null;
        }

        var matches = _catalog.Where(item =>
            item.Slug.Equals(query, StringComparison.OrdinalIgnoreCase)
            || item.Language.Equals(query, StringComparison.OrdinalIgnoreCase)
            || item.DisplayText.Equals(query, StringComparison.OrdinalIgnoreCase))
            .ToList();
        if (matches.Count == 0)
        {
            matches = _catalog.Where(item =>
                item.Language.Contains(query, StringComparison.OrdinalIgnoreCase)
                || item.Slug.Contains(query, StringComparison.OrdinalIgnoreCase))
                .ToList();
        }
        if (matches.Count == 0)
        {
            return null;
        }

        return matches
            .OrderByDescending(item => !string.IsNullOrWhiteSpace(preferredSource)
                && item.Source.Equals(preferredSource, StringComparison.OrdinalIgnoreCase))
            .ThenByDescending(item => item.Version == "latest")
            .ThenBy(item => item.Source, StringComparer.OrdinalIgnoreCase)
            .ThenBy(item => item.Language, StringComparer.OrdinalIgnoreCase)
            .First();
    }

    private void ValidateForm()
    {
        var isReady = App.MainViewModel.BackendReady && !string.IsNullOrWhiteSpace(LanguageBox.Text);
        StartRunButton.IsEnabled = isReady;
        PreviewButton.IsEnabled = isReady && ValidateOnlyBox.IsChecked != true;
    }

    private JsonObject BuildRunPayload(string? source, bool dryRun)
    {
        var requestedLanguage = _selectedLanguage is not null
            && LanguageBox.Text.Trim().Equals(_selectedLanguage.Language, StringComparison.OrdinalIgnoreCase)
            ? _selectedLanguage.Slug
            : LanguageBox.Text.Trim();
        return new JsonObject
        {
            ["language"] = requestedLanguage,
            ["mode"] = ModeBox.SelectedItem?.ToString() ?? "important",
            ["source"] = source,
            ["validate_only"] = ValidateOnlyBox.IsChecked == true,
            ["force_refresh"] = ForceRefreshBox.IsChecked == true,
            ["dry_run"] = dryRun,
        };
    }

    private async Task<JsonObject?> WaitForJobSummaryAsync(string jobId)
    {
        var deadline = DateTimeOffset.UtcNow.AddSeconds(60);
        while (DateTimeOffset.UtcNow < deadline)
        {
            var status = await App.BackendHost.Client.GetJobAsync(jobId) as JsonObject;
            var state = status?["status"]?.GetValue<string>() ?? "";
            if (state == "completed")
            {
                return status?["summary"] as JsonObject;
            }
            if (state is "failed" or "cancelled")
            {
                throw new InvalidOperationException(status?["error"]?.GetValue<string>() ?? $"Preview {state}.");
            }
            await Task.Delay(250);
        }
        throw new TimeoutException("Preview timed out waiting for backend result.");
    }

    private async Task ShowPreviewDialogAsync(JsonObject summary)
    {
        var language = summary["language"]?.GetValue<string>() ?? LanguageBox.Text.Trim();
        var source = summary["source"]?.GetValue<string>() ?? "unknown";
        var slug = summary["slug"]?.GetValue<string>() ?? language;
        var count = summary["estimated_document_count"]?.GetValue<int?>();
        var sizeHint = summary["estimated_size_hint"]?.GetValue<int?>();
        var topics = (summary["topics"] as JsonArray)?.Select(node => node?.GetValue<string>() ?? "").Where(text => !string.IsNullOrWhiteSpace(text)).ToList() ?? [];
        var notes = (summary["notes"] as JsonArray)?.Select(node => node?.GetValue<string>() ?? "").Where(text => !string.IsNullOrWhiteSpace(text)).ToList() ?? [];

        var text = $"Language: {language}\n"
            + $"Source: {source}\n"
            + $"Slug: {slug}\n"
            + $"Estimated documents: {(count.HasValue ? count.Value.ToString() : "unknown")}\n"
            + $"Estimated size: {(sizeHint.HasValue ? FormatBytes(sizeHint.Value) : "unknown")}\n\n"
            + $"Topics:\n- {(topics.Count > 0 ? string.Join("\n- ", topics) : "No topic estimate available.")}";
        if (notes.Count > 0)
        {
            text += $"\n\nNotes:\n- {string.Join("\n- ", notes)}";
        }

        var dialog = new ContentDialog
        {
            Title = "Preview result",
            Content = new ScrollViewer
            {
                MaxHeight = 420,
                Content = new TextBox
                {
                    Text = text,
                    AcceptsReturn = true,
                    TextWrapping = TextWrapping.Wrap,
                    IsReadOnly = true,
                },
            },
            CloseButtonText = "Close",
            XamlRoot = XamlRoot,
        };
        await dialog.ShowAsync();
    }

    private static string FormatBytes(int bytes)
    {
        var value = (double)bytes;
        string[] units = ["B", "KB", "MB", "GB"];
        var unit = 0;
        while (value >= 1024 && unit < units.Length - 1)
        {
            value /= 1024;
            unit++;
        }
        return $"{value:0.#} {units[unit]}";
    }
}
