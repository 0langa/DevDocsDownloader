using System.ComponentModel;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class BulkPage : Page
{
    private static readonly string[] FallbackSources = ["Any (auto)", "dash", "devdocs", "mdn"];

    // ---------------------------------------------------------------------------
    // Inner model
    // ---------------------------------------------------------------------------

    private sealed class CatalogEntry
    {
        public required string Language { get; init; }
        public required string Source { get; init; }
        public required string Slug { get; init; }

        // "latest" when backend returned empty version string
        public string Version { get; init; } = "latest";

        public string DisplayText => Version == "latest"
            ? $"{Language} ({Source})"
            : $"{Language} {Version} ({Source})";

        public override string ToString() => DisplayText;
    }

    // ---------------------------------------------------------------------------
    // State
    // ---------------------------------------------------------------------------

    private readonly List<CatalogEntry> _catalog = [];
    private readonly List<CatalogEntry> _selectedLanguages = [];
    private bool _initialized;

    // ---------------------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------------------

    public BulkPage()
    {
        InitializeComponent();
        App.MainViewModel.PropertyChanged += OnShellPropertyChanged;
        EventsList.ItemsSource = App.MainViewModel.ActivityLines;
        SourceBox.ItemsSource = FallbackSources;
    }

    // ---------------------------------------------------------------------------
    // Navigation
    // ---------------------------------------------------------------------------

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (_initialized)
        {
            RefreshProgress();
            return;
        }
        _initialized = true;

        // Mode, version filter, concurrency, policy
        ModeBox.SelectedItem = App.MainViewModel.DefaultMode;
        VersionFilterBox.SelectedIndex = 0; // "Latest only"
        ConcurrencyBox.Text = App.MainViewModel.LanguageConcurrency.ToString();
        PolicyBox.SelectedItem = App.MainViewModel.BulkConcurrencyPolicy;

        // Source dropdown
        PopulateSourceBox();

        RefreshProgress();
        ValidateForm();

        // Load language catalog in the background — UI is usable while loading
        await LoadCatalogAsync();
    }

    // ---------------------------------------------------------------------------
    // Public API called from LanguagesPage
    // ---------------------------------------------------------------------------

    public void AddLanguage(string language)
    {
        // Find best matching catalog entry (latest version preferred)
        var match = FindBestMatch(language);
        match ??= new CatalogEntry { Language = language, Source = "auto", Slug = language };
        AddEntryToSelection(match);
        ValidateForm();
    }

    // ---------------------------------------------------------------------------
    // Catalog loading
    // ---------------------------------------------------------------------------

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
                if (string.IsNullOrWhiteSpace(language))
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
            ValidateForm();
        }
        catch
        {
            // Catalog is best-effort — user can still type slugs manually
            PopulateSourceBox();
        }
    }

    // ---------------------------------------------------------------------------
    // Language search (AutoSuggestBox)
    // ---------------------------------------------------------------------------

    private void OnLanguageSearchTextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput)
        {
            return;
        }
        var query = sender.Text.Trim();
        if (string.IsNullOrWhiteSpace(query))
        {
            sender.ItemsSource = null;
            return;
        }
        var latestOnly = VersionFilterBox.SelectedIndex == 0;
        var pool = latestOnly ? ApplyLatestFilter(_catalog) : (IEnumerable<CatalogEntry>)_catalog;
        var filtered = pool
            .Where(item => item.Language.Contains(query, StringComparison.OrdinalIgnoreCase)
                        || item.Slug.Contains(query, StringComparison.OrdinalIgnoreCase))
            .Take(30)
            .ToList();
        sender.ItemsSource = filtered;
    }

    private void OnLanguageSuggestionChosen(AutoSuggestBox sender, AutoSuggestBoxSuggestionChosenEventArgs args)
    {
        if (args.SelectedItem is CatalogEntry entry)
        {
            AddSelectedEntry(entry);
        }
    }

    private void OnLanguageQuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        // args.ChosenSuggestion is set when user picked from dropdown; QueryText is set for Enter key.
        CatalogEntry? entry = args.ChosenSuggestion as CatalogEntry;
        if (entry is null)
        {
            var query = (args.QueryText ?? "").Trim();
            if (!string.IsNullOrWhiteSpace(query))
            {
                entry = FindBestMatch(query);
            }
        }

        if (entry is not null)
        {
            AddSelectedEntry(entry);
            return;
        }

        sender.Text = "";
        sender.ItemsSource = null;
        ValidateForm();
    }

    // ---------------------------------------------------------------------------
    // Selected languages list management
    // ---------------------------------------------------------------------------

    private void AddEntryToSelection(CatalogEntry entry)
    {
        // Deduplicate on slug+source
        if (_selectedLanguages.Any(item => item.Slug == entry.Slug && item.Source == entry.Source))
        {
            return;
        }
        _selectedLanguages.Add(entry);
        RebuildSelectedList();
    }

    private void OnRemoveLanguage(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is CatalogEntry entry)
        {
            _selectedLanguages.Remove(entry);
            RebuildSelectedList();
            ValidateForm();
        }
    }

    private void OnClearLanguages(object sender, RoutedEventArgs e)
    {
        _selectedLanguages.Clear();
        RebuildSelectedList();
        ValidateForm();
    }

    private void RebuildSelectedList()
    {
        SelectedLanguagesList.Items.Clear();
        foreach (var entry in _selectedLanguages)
        {
            var panel = new Grid();
            panel.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            panel.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var label = new TextBlock
            {
                Text = entry.DisplayText,
                VerticalAlignment = VerticalAlignment.Center,
                TextTrimming = Microsoft.UI.Xaml.TextTrimming.CharacterEllipsis,
            };
            Grid.SetColumn(label, 0);

            var localEntry = entry; // Capture for closure
            var removeBtn = new Button
            {
                Content = "✕",
                Tag = localEntry,
                Padding = new Thickness(6, 2, 6, 2),
                FontSize = 11,
                Margin = new Thickness(8, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Center,
            };
            removeBtn.Click += OnRemoveLanguage;
            Grid.SetColumn(removeBtn, 1);

            panel.Children.Add(label);
            panel.Children.Add(removeBtn);

            SelectedLanguagesList.Items.Add(panel);
        }

        var count = _selectedLanguages.Count;
        SelectedCountText.Text = count == 0 ? "No languages selected" : $"{count} language(s) selected";
        ClearLanguagesButton.IsEnabled = count > 0;
    }

    // ---------------------------------------------------------------------------
    // Version filter
    // ---------------------------------------------------------------------------

    private void OnVersionFilterChanged(object sender, SelectionChangedEventArgs e)
    {
        // Clear search suggestions when filter changes (stale results)
        LanguageSearchBox.ItemsSource = null;
        OnFormChanged(sender, e);
    }

    private static IEnumerable<CatalogEntry> ApplyLatestFilter(IEnumerable<CatalogEntry> entries)
    {
        // Group by (source, slug family = part before '~').
        // For each group prefer the versionless entry ("latest"); if all are versioned take highest.
        return entries
            .GroupBy(item => $"{item.Source}|{SlugFamily(item.Slug)}")
            .Select(group =>
            {
                var versionless = group.Where(item => item.Version == "latest").ToList();
                if (versionless.Count > 0)
                {
                    return versionless.OrderBy(item => item.Source).First();
                }
                // All versioned — pick highest major version
                return group
                    .OrderByDescending(item => MajorVersion(item.Version))
                    .ThenByDescending(item => item.Version, StringComparer.OrdinalIgnoreCase)
                    .First();
            });
    }

    private static string SlugFamily(string slug)
    {
        var idx = slug.IndexOf('~');
        return idx >= 0 ? slug[..idx] : slug;
    }

    private static int MajorVersion(string version)
    {
        var match = Regex.Match(version, @"^\d+");
        return match.Success && int.TryParse(match.Value, out var n) ? n : 0;
    }

    // ---------------------------------------------------------------------------
    // Download All
    // ---------------------------------------------------------------------------

    private async void OnDownloadAll(object sender, RoutedEventArgs e)
    {
        try
        {
            var latestOnly = VersionFilterBox.SelectedIndex == 0;
            IEnumerable<CatalogEntry> pool = latestOnly ? ApplyLatestFilter(_catalog) : _catalog;

            // Populate selection and launch immediately
            _selectedLanguages.Clear();
            foreach (var entry in pool.OrderBy(item => item.Language, StringComparer.OrdinalIgnoreCase))
            {
                _selectedLanguages.Add(entry);
            }
            RebuildSelectedList();
            ValidateForm();

            if (_selectedLanguages.Count == 0)
            {
                return;
            }
            await StartBulkRunAsync();
        }
        catch (Exception exc)
        {
            ActivityText.Text = exc.Message;
        }
    }

    // ---------------------------------------------------------------------------
    // Start bulk run
    // ---------------------------------------------------------------------------

    private async void OnStartBulk(object sender, RoutedEventArgs e)
    {
        try
        {
            await StartBulkRunAsync();
        }
        catch (Exception exc)
        {
            ActivityText.Text = exc.Message;
        }
    }

    private async Task StartBulkRunAsync()
    {
        if (_selectedLanguages.Count == 0)
        {
            return;
        }

        // Send slugs — the backend registry resolves them via exact slug matching
        var slugs = _selectedLanguages.Select(item => item.Slug).Distinct().ToArray();
        var source = GetSelectedSource();

        var payload = new JsonObject
        {
            ["languages"] = new JsonArray(slugs.Select(item => JsonValue.Create(item)).ToArray()),
            ["mode"] = ModeBox.SelectedItem?.ToString() ?? "important",
            ["language_concurrency"] = int.TryParse(ConcurrencyBox.Text, out var concurrency) ? concurrency : 3,
            ["concurrency_policy"] = PolicyBox.SelectedItem?.ToString() ?? "static",
        };
        if (!string.IsNullOrWhiteSpace(source))
        {
            payload["source"] = source;
        }

        var result = await App.BackendHost.Client.StartBulkAsync(payload);
        var jobId = result?["id"]?.GetValue<string>() ?? "";
        var status = result?["status"]?.GetValue<string>() ?? "running";
        var queuePosition = result?["queue_position"]?.GetValue<int?>();
        App.MainViewModel.LanguageConcurrency = int.TryParse(ConcurrencyBox.Text, out var parsed)
            ? parsed : App.MainViewModel.LanguageConcurrency;
        App.MainViewModel.BulkConcurrencyPolicy = payload["concurrency_policy"]?.GetValue<string>()
            ?? App.MainViewModel.BulkConcurrencyPolicy;
        await App.MainViewModel.StartTrackingJobAsync(
            jobId,
            $"{slugs.Length} language(s)",
            "run_bulk",
            status,
            queuePosition);
        RefreshProgress();
    }

    // ---------------------------------------------------------------------------
    // Cancel
    // ---------------------------------------------------------------------------

    private async void OnCancelJob(object sender, RoutedEventArgs e)
    {
        await App.MainViewModel.CancelActiveJobAsync();
    }

    // ---------------------------------------------------------------------------
    // Source helper
    // ---------------------------------------------------------------------------

    private string? GetSelectedSource()
    {
        var selected = SourceBox.SelectedItem?.ToString();
        return selected == "Any (auto)" || string.IsNullOrWhiteSpace(selected) ? null : selected;
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
        SourceBox.SelectedItem = sources.FirstOrDefault(item => item.Equals(current, StringComparison.OrdinalIgnoreCase))
            ?? sources.First();
    }

    // ---------------------------------------------------------------------------
    // Form validation
    // ---------------------------------------------------------------------------

    private void OnFormChanged(object sender, object e) => ValidateForm();

    private void ValidateForm()
    {
        StartBulkButton.IsEnabled = App.MainViewModel.BackendReady && _selectedLanguages.Count > 0;
        DownloadAllButton.IsEnabled = App.MainViewModel.BackendReady && _catalog.Count > 0;
    }

    // ---------------------------------------------------------------------------
    // Progress
    // ---------------------------------------------------------------------------

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
        ValidateForm();
    }

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    private CatalogEntry? FindBestMatch(string language)
    {
        var lower = language.Trim().ToLowerInvariant();
        // Exact slug match first
        var slugMatch = _catalog.FirstOrDefault(item =>
            item.Slug.Equals(lower, StringComparison.OrdinalIgnoreCase));
        if (slugMatch is not null)
        {
            return slugMatch;
        }
        // Display name match — prefer latest (versionless)
        var nameMatches = _catalog
            .Where(item => item.Language.Equals(language.Trim(), StringComparison.OrdinalIgnoreCase))
            .ToList();
        if (nameMatches.Count == 0)
        {
            return null;
        }
        return nameMatches.FirstOrDefault(item => item.Version == "latest")
            ?? nameMatches.OrderByDescending(item => MajorVersion(item.Version)).First();
    }

    private void AddSelectedEntry(CatalogEntry entry)
    {
        AddEntryToSelection(entry);
        LanguageSearchBox.Text = "";
        LanguageSearchBox.ItemsSource = null;
        ValidateForm();
    }
}
