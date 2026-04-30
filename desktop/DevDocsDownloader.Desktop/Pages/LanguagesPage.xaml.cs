using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class LanguagesPage : Page
{
    private sealed class LanguageItem
    {
        public required string Language { get; init; }
        public required string Source { get; init; }
        public required string Slug { get; init; }
        public string Version { get; init; } = "";
        public int SizeHint { get; init; }
        public string Confidence { get; init; } = "";
        public List<string> Categories { get; init; } = [];

        public override string ToString()
        {
            var baseText = string.IsNullOrWhiteSpace(Version) ? Language : $"{Language} {Version}";
            if (Source.Equals("dash", StringComparison.OrdinalIgnoreCase) && SizeHint > 0)
            {
                baseText += $" [{FormatBytes(SizeHint)}]";
            }
            if (!string.IsNullOrWhiteSpace(Confidence))
            {
                baseText += $" <{Confidence}>";
            }
            return baseText;
        }
    }

    private readonly List<LanguageItem> _languages = [];
    private Dictionary<string, List<string>> _presetMap = [];
    private LanguageItem? _selectedLanguage;
    private bool _initialized;

    public LanguagesPage()
    {
        InitializeComponent();
        ViewModeBox.SelectedIndex = App.MainViewModel.LanguageTreeMode == "category" ? 1 : 0;
        SearchBox.Text = App.MainViewModel.LanguageSearch;
        SourceFilterBox.Items.Add("All sources");
        SourceFilterBox.SelectedIndex = 0;
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
        await RefreshAsync(forceRefresh: true);
    }

    private void OnFiltersChanged(object sender, object e)
    {
        App.MainViewModel.LanguageTreeMode = ViewModeBox.SelectedIndex == 1 ? "category" : "source";
        App.MainViewModel.LanguageSearch = SearchBox.Text;
        RebuildTree();
    }

    private void OnTreeSelectionChanged(TreeView sender, TreeViewSelectionChangedEventArgs args)
    {
        if (sender.SelectedNode?.Content is not LanguageItem item)
        {
            return;
        }
        _selectedLanguage = item;
        App.MainViewModel.RecordLanguageSelection(item.Language, item.Source);
        SelectionTitleText.Text = $"{item.Language} {item.Version}".Trim();
        SelectionSourceText.Text = $"Source: {item.Source}";
        SelectionSlugText.Text = $"Slug: {item.Slug}";
        SelectionCategoriesText.Text = item.Categories.Count == 0
            ? "Categories: Uncategorized"
            : $"Categories: {string.Join(", ", item.Categories)}";
        UseInRunButton.IsEnabled = true;
        UseInBulkButton.IsEnabled = true;
    }

    private void OnUseInRun(object sender, RoutedEventArgs e)
    {
        if (_selectedLanguage is null)
        {
            return;
        }
        var runPage = App.MainWindow.GetCachedPage<RunPage>();
        runPage?.ApplySuggestedLanguage(_selectedLanguage.Language, _selectedLanguage.Source);
        App.MainWindow.NavigateTo("RunPage");
    }

    private void OnUseInBulk(object sender, RoutedEventArgs e)
    {
        if (_selectedLanguage is null)
        {
            return;
        }
        var bulkPage = App.MainWindow.GetCachedPage<BulkPage>();
        bulkPage?.AddLanguage(_selectedLanguage.Language);
        App.MainWindow.NavigateTo("BulkPage");
    }

    private async Task RefreshAsync(bool forceRefresh = false)
    {
        try
        {
            SummaryText.Text = "Loading source catalogs...";
            string refreshSummary = "";
            if (forceRefresh)
            {
                refreshSummary = SummarizeRefreshResult(await App.BackendHost.Client.RefreshCatalogsAsync());
            }
            var presetNode = await App.BackendHost.Client.GetPresetsAsync();
            _presetMap = ParsePresets(presetNode as JsonObject);

            var result = await App.BackendHost.Client.GetLanguagesAsync();
            _languages.Clear();
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
                _languages.Add(new LanguageItem
                {
                    Language = language,
                    Source = source,
                    Slug = slug,
                    Version = string.IsNullOrWhiteSpace(version) ? "latest" : version,
                    SizeHint = row["size_hint"]?.GetValue<int?>() ?? 0,
                    Confidence = row["confidence"]?.GetValue<string>() ?? "",
                    Categories = ResolveCategories(language),
                });
            }

            LoadSourceFilter();
            RebuildTree();
            await UpdateStalenessSummaryAsync();
            if (!string.IsNullOrWhiteSpace(refreshSummary))
            {
                SummaryText.Text = refreshSummary;
            }
        }
        catch (Exception exc)
        {
            SummaryText.Text = exc.Message;
        }
    }

    private async Task UpdateStalenessSummaryAsync()
    {
        try
        {
            var health = await App.BackendHost.Client.GetSourcesHealthAsync() as JsonObject;
            if (health is null)
            {
                return;
            }
            var stale = new List<string>();
            foreach (var source in new[] { "devdocs", "mdn", "dash", "web_page" })
            {
                var entry = health[source] as JsonObject;
                var age = entry?["catalog_age_hours"]?.GetValue<double?>() ?? 0;
                if (age >= App.MainViewModel.CatalogStaleWarningDays * 24)
                {
                    stale.Add($"{source}:{age / 24:0.#}d");
                }
            }
            if (stale.Count > 0)
            {
                SummaryText.Text += $"  |  Stale catalogs: {string.Join(", ", stale)}. Use Refresh.";
            }
        }
        catch
        {
        }
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

    private void RebuildTree()
    {
        LanguageTree.RootNodes.Clear();
        var mode = ViewModeBox.SelectedIndex == 1 ? "category" : "source";
        var search = SearchBox.Text.Trim();
        var sourceFilter = SourceFilterBox.SelectedItem?.ToString() ?? "All sources";
        var filtered = _languages
            .Where(item => sourceFilter == "All sources" || item.Source.Equals(sourceFilter, StringComparison.OrdinalIgnoreCase))
            .Where(item => MatchesSearch(item, search))
            .OrderBy(item => item.Source)
            .ThenBy(item => item.Language)
            .ThenByDescending(item => item.Version)
            .ToList();

        if (mode == "category")
        {
            BuildCategoryFirstTree(filtered);
        }
        else
        {
            BuildSourceFirstTree(filtered);
        }

        SummaryText.Text = $"Showing {filtered.Count:N0} catalog entries across {filtered.Select(item => item.Source).Distinct().Count()} sources.";
        if (filtered.Count == 0)
        {
            SelectionTitleText.Text = "No matching languages.";
            SelectionSourceText.Text = "";
            SelectionSlugText.Text = "";
            SelectionCategoriesText.Text = "";
            UseInRunButton.IsEnabled = false;
            UseInBulkButton.IsEnabled = false;
        }
    }

    private void BuildSourceFirstTree(IEnumerable<LanguageItem> items)
    {
        foreach (var sourceGroup in items.GroupBy(item => item.Source).OrderBy(group => group.Key))
        {
            var sourceNode = new TreeViewNode { Content = $"{sourceGroup.Key} ({sourceGroup.Count()})", IsExpanded = true };
            foreach (var languageGroup in sourceGroup.GroupBy(item => item.Language).OrderBy(group => group.Key))
            {
                var languageNode = new TreeViewNode { Content = $"{languageGroup.Key} ({languageGroup.Count()})", IsExpanded = false };
                foreach (var versionItem in languageGroup.OrderByDescending(item => item.Version))
                {
                    languageNode.Children.Add(new TreeViewNode
                    {
                        Content = versionItem,
                    });
                }
                sourceNode.Children.Add(languageNode);
            }
            LanguageTree.RootNodes.Add(sourceNode);
        }
    }

    private void BuildCategoryFirstTree(IEnumerable<LanguageItem> items)
    {
        var categorized = items
            .SelectMany(item => item.Categories.DefaultIfEmpty("Uncategorized"), (item, category) => (item, category))
            .GroupBy(pair => pair.category)
            .OrderBy(group => group.Key);
        foreach (var categoryGroup in categorized)
        {
            var categoryNode = new TreeViewNode { Content = $"{categoryGroup.Key} ({categoryGroup.Count()})", IsExpanded = true };
            foreach (var sourceGroup in categoryGroup.GroupBy(pair => pair.item.Source).OrderBy(group => group.Key))
            {
                var sourceNode = new TreeViewNode { Content = $"{sourceGroup.Key} ({sourceGroup.Count()})", IsExpanded = false };
                foreach (var languageGroup in sourceGroup.GroupBy(pair => pair.item.Language).OrderBy(group => group.Key))
                {
                    var languageNode = new TreeViewNode { Content = $"{languageGroup.Key} ({languageGroup.Count()})", IsExpanded = false };
                    foreach (var pair in languageGroup.OrderByDescending(group => group.item.Version))
                    {
                        languageNode.Children.Add(new TreeViewNode { Content = pair.item });
                    }
                    sourceNode.Children.Add(languageNode);
                }
                categoryNode.Children.Add(sourceNode);
            }
            LanguageTree.RootNodes.Add(categoryNode);
        }
    }

    private void LoadSourceFilter()
    {
        var current = SourceFilterBox.SelectedItem?.ToString() ?? "All sources";
        SourceFilterBox.Items.Clear();
        SourceFilterBox.Items.Add("All sources");
        foreach (var source in _languages.Select(item => item.Source).Distinct().OrderBy(item => item))
        {
            SourceFilterBox.Items.Add(source);
        }
        SourceFilterBox.SelectedItem = SourceFilterBox.Items.Cast<object?>().FirstOrDefault(item => item?.ToString() == current)
            ?? "All sources";
    }

    private static bool MatchesSearch(LanguageItem item, string search)
    {
        if (string.IsNullOrWhiteSpace(search))
        {
            return true;
        }
        return item.Language.Contains(search, StringComparison.OrdinalIgnoreCase)
            || item.Source.Contains(search, StringComparison.OrdinalIgnoreCase)
            || item.Version.Contains(search, StringComparison.OrdinalIgnoreCase)
            || item.Slug.Contains(search, StringComparison.OrdinalIgnoreCase)
            || item.Categories.Any(category => category.Contains(search, StringComparison.OrdinalIgnoreCase));
    }

    private List<string> ResolveCategories(string language)
    {
        var categories = _presetMap
            .Where(pair => pair.Value.Any(item => item.Equals(language, StringComparison.OrdinalIgnoreCase)))
            .Select(pair => pair.Key)
            .OrderBy(item => item)
            .ToList();
        return categories;
    }

    private static Dictionary<string, List<string>> ParsePresets(JsonObject? presets)
    {
        var result = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
        if (presets is null)
        {
            return result;
        }
        foreach (var pair in presets)
        {
            if (pair.Value is not JsonArray values)
            {
                continue;
            }
            result[pair.Key] = values
                .Select(value => value?.GetValue<string>() ?? "")
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .ToList();
        }
        return result;
    }

    private static string SummarizeRefreshResult(JsonNode? payload)
    {
        if (payload is not JsonArray rows || rows.Count == 0)
        {
            return "Catalog refresh completed.";
        }

        var refreshed = 0;
        var fallbacks = new List<string>();
        var failures = new List<string>();
        foreach (var row in rows.OfType<JsonObject>())
        {
            var source = row["source"]?.GetValue<string>() ?? "unknown";
            var status = row["status"]?.GetValue<string>() ?? "";
            if (status == "failed")
            {
                failures.Add(source);
            }
            else if (status == "fallback")
            {
                fallbacks.Add(source);
            }
            else
            {
                refreshed += 1;
            }
        }

        var parts = new List<string> { $"Catalog refresh: {refreshed} refreshed" };
        if (fallbacks.Count > 0)
        {
            parts.Add($"fallback: {string.Join(", ", fallbacks)}");
        }
        if (failures.Count > 0)
        {
            parts.Add($"failed: {string.Join(", ", failures)}");
        }
        return string.Join(" | ", parts);
    }
}
