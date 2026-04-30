using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class CachePage : Page
{
    private sealed class CacheSourceCard
    {
        public required string Source { get; init; }
        public required string SummaryText { get; init; }

        public override string ToString() => SummaryText;
    }

    private sealed class CacheEntryItem
    {
        public required string Source { get; init; }
        public required string Slug { get; init; }
        public required string CacheKey { get; init; }
        public required string Path { get; init; }
        public required long ByteCount { get; init; }
        public required string FetchedAt { get; init; }
        public required string Policy { get; init; }
        public required string NextRefreshDue { get; init; }
        public required JsonObject Raw { get; init; }

        public override string ToString() =>
            $"{Source} / {Slug}  |  {FormatSize(ByteCount)}  |  {Policy}  |  {FormatTimestamp(FetchedAt)}";
    }

    private readonly Dictionary<string, JsonObject> _rawMetadata = new(StringComparer.OrdinalIgnoreCase);
    private List<CacheSourceCard> _sourceCards = [];
    private List<CacheEntryItem> _entries = [];
    private bool _initialized;
    private int _maxCacheSizeMb = 2048;

    public CachePage()
    {
        InitializeComponent();
        SortBox.SelectedIndex = 0;
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
        await RefreshAsync();
    }

    private void OnSortChanged(object sender, SelectionChangedEventArgs e)
    {
        RenderEntries();
    }

    private void OnFilterChanged(object sender, SelectionChangedEventArgs e)
    {
        RenderEntries();
    }

    private void OnSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CacheList.SelectedItem is not CacheEntryItem item)
        {
            DetailTitleText.Text = "Select a cache entry.";
            ContentBox.Text = "";
            RefreshEntryButton.IsEnabled = false;
            DeleteEntryButton.IsEnabled = false;
            return;
        }

        DetailTitleText.Text = $"{item.Source} / {item.Slug}";
        ContentBox.Text = BuildDetailText(item);
        RefreshEntryButton.IsEnabled = true;
        DeleteEntryButton.IsEnabled = true;
    }

    private async void OnRefreshEntry(object sender, RoutedEventArgs e)
    {
        if (CacheList.SelectedItem is not CacheEntryItem item)
        {
            return;
        }

        try
        {
            StatusText.Text = $"Refreshing {item.Source}/{item.Slug}...";
            await App.BackendHost.Client.RefreshCacheEntryAsync(item.Source, item.Slug);
            await RefreshAsync();
            StatusText.Text = $"Refreshed {item.Source}/{item.Slug}.";
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async void OnDeleteEntry(object sender, RoutedEventArgs e)
    {
        if (CacheList.SelectedItem is not CacheEntryItem item)
        {
            return;
        }

        var dialog = new ContentDialog
        {
            Title = $"Delete cache entry for {item.Source}/{item.Slug}?",
            Content = "This removes the cached source files for the selected entry only.",
            PrimaryButtonText = "Delete",
            CloseButtonText = "Cancel",
            XamlRoot = XamlRoot,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        try
        {
            await App.BackendHost.Client.DeleteCacheEntryAsync(item.Source, item.Slug);
            await RefreshAsync();
            StatusText.Text = $"Deleted {item.Source}/{item.Slug}.";
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async void OnClearSource(object sender, RoutedEventArgs e)
    {
        var source = GetSelectedSourceFilter();
        if (string.IsNullOrWhiteSpace(source))
        {
            StatusText.Text = "Choose a source filter before clearing a source cache.";
            return;
        }

        var dialog = new ContentDialog
        {
            Title = $"Clear all {source} cache?",
            Content = $"This removes every cached {source} entry.",
            PrimaryButtonText = "Clear",
            CloseButtonText = "Cancel",
            XamlRoot = XamlRoot,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        try
        {
            await App.BackendHost.Client.ClearSourceCacheAsync(source);
            await RefreshAsync();
            StatusText.Text = $"Cleared {source} cache.";
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async void OnClearAll(object sender, RoutedEventArgs e)
    {
        var dialog = new ContentDialog
        {
            Title = "Clear all cache?",
            Content = "This removes every cached source file, catalog, and archive. The next run will redownload everything.",
            PrimaryButtonText = "Clear all",
            CloseButtonText = "Cancel",
            XamlRoot = XamlRoot,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        try
        {
            await App.BackendHost.Client.ClearAllCacheAsync();
            await RefreshAsync();
            StatusText.Text = "Cleared all cache.";
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async Task RefreshAsync()
    {
        try
        {
            StatusText.Text = "Loading cache summary...";
            var summary = await App.BackendHost.Client.GetCacheSummaryAsync() as JsonObject;
            var rawMetadata = await App.BackendHost.Client.GetCacheMetadataAsync();

            _rawMetadata.Clear();
            foreach (var node in rawMetadata ?? [])
            {
                if (node is not JsonObject item)
                {
                    continue;
                }

                var source = item["source"]?.GetValue<string>() ?? _sourceFromPath(item["path"]?.GetValue<string>() ?? "");
                var slug = _slugFromCacheKey(item["cache_key"]?.GetValue<string>() ?? "", item["path"]?.GetValue<string>() ?? "");
                _rawMetadata[$"{source}/{slug}"] = item;
            }

            _maxCacheSizeMb = summary?["max_cache_size_mb"]?.GetValue<int?>() ?? App.MainViewModel.MaxCacheSizeMb;
            UsageText.Text = BuildUsageText(summary);
            UsageBar.Maximum = Math.Max(1, (summary?["max_cache_size_bytes"]?.GetValue<long?>() ?? (long)_maxCacheSizeMb * 1024 * 1024));
            UsageBar.Value = summary?["total_bytes"]?.GetValue<long?>() ?? 0;

            var usageRatio = UsageBar.Maximum <= 0 ? 0 : UsageBar.Value / UsageBar.Maximum;
            UsageStatusText.Text = usageRatio switch
            {
                >= 0.95 => "Cache budget nearly full",
                >= 0.75 => "Cache budget getting tight",
                _ => "Cache budget healthy",
            };

            _sourceCards = (summary?["sources"] as JsonArray ?? [])
                .OfType<JsonObject>()
                .Select(item => new CacheSourceCard
                {
                    Source = item["source"]?.GetValue<string>() ?? "unknown",
                    SummaryText =
                        $"{item["source"]?.GetValue<string>() ?? "unknown"}\n"
                        + $"{FormatSize(item["total_bytes"]?.GetValue<long?>() ?? 0)}"
                        + $" across {item["entry_count"]?.GetValue<int?>() ?? 0} entries\n"
                        + $"Oldest: {FormatTimestamp(item["oldest_entry_at"]?.GetValue<string>() ?? "")}\n"
                        + $"Newest: {FormatTimestamp(item["newest_entry_at"]?.GetValue<string>() ?? "")}",
                })
                .ToList();
            SourceCardsList.ItemsSource = _sourceCards;

            _entries = (summary?["entries"] as JsonArray ?? [])
                .OfType<JsonObject>()
                .Select(item =>
                {
                    var source = item["source"]?.GetValue<string>() ?? "unknown";
                    var slug = item["slug"]?.GetValue<string>() ?? "cache";
                    _rawMetadata.TryGetValue($"{source}/{slug}", out var raw);
                    return new CacheEntryItem
                    {
                        Source = source,
                        Slug = slug,
                        CacheKey = item["cache_key"]?.GetValue<string>() ?? "",
                        Path = item["path"]?.GetValue<string>() ?? "",
                        ByteCount = item["byte_count"]?.GetValue<long?>() ?? 0,
                        FetchedAt = item["fetched_at"]?.GetValue<string>() ?? "",
                        Policy = item["policy"]?.GetValue<string>() ?? "",
                        NextRefreshDue = item["next_refresh_due"]?.GetValue<string>() ?? "",
                        Raw = raw ?? item,
                    };
                })
                .ToList();

            PopulateSourceFilter();
            RenderEntries();
            StatusText.Text = $"Loaded {_entries.Count} cache entries from {summary?["cache_root"]?.GetValue<string>() ?? "cache root"}.";
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
            DetailTitleText.Text = exc.Message;
            ContentBox.Text = "";
        }
    }

    private void PopulateSourceFilter()
    {
        var current = SourceFilterBox.SelectedItem?.ToString();
        var sources = _entries
            .Select(item => item.Source)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(item => item, StringComparer.OrdinalIgnoreCase)
            .ToList();
        sources.Insert(0, "All sources");
        SourceFilterBox.ItemsSource = sources;
        SourceFilterBox.SelectedItem = sources.FirstOrDefault(item => item.Equals(current, StringComparison.OrdinalIgnoreCase)) ?? sources[0];
    }

    private void RenderEntries()
    {
        IEnumerable<CacheEntryItem> ordered = _entries;
        var sourceFilter = GetSelectedSourceFilter();
        if (!string.IsNullOrWhiteSpace(sourceFilter))
        {
            ordered = ordered.Where(item => item.Source.Equals(sourceFilter, StringComparison.OrdinalIgnoreCase));
        }

        ordered = SortBox.SelectedIndex switch
        {
            1 => ordered.OrderByDescending(item => item.FetchedAt),
            2 => ordered.OrderBy(item => item.Policy).ThenBy(item => item.Source),
            3 => ordered.OrderByDescending(item => item.ByteCount).ThenBy(item => item.Source),
            _ => ordered.OrderBy(item => item.Source).ThenBy(item => item.Slug),
        };

        var rendered = ordered.ToList();
        CacheList.ItemsSource = rendered;
        if (rendered.Count == 0)
        {
            DetailTitleText.Text = "No cache entries found.";
            ContentBox.Text = "";
            RefreshEntryButton.IsEnabled = false;
            DeleteEntryButton.IsEnabled = false;
        }
    }

    private string? GetSelectedSourceFilter()
    {
        var selected = SourceFilterBox.SelectedItem?.ToString();
        return string.Equals(selected, "All sources", StringComparison.OrdinalIgnoreCase) ? null : selected;
    }

    private static string BuildUsageText(JsonObject? summary)
    {
        var used = summary?["total_bytes"]?.GetValue<long?>() ?? 0;
        var maxBytes = summary?["max_cache_size_bytes"]?.GetValue<long?>() ?? 0;
        var maxMb = summary?["max_cache_size_mb"]?.GetValue<int?>() ?? 2048;
        return $"Cache usage: {FormatSize(used)} / {FormatSize(maxBytes)} ({maxMb} MB budget)";
    }

    private static string BuildDetailText(CacheEntryItem item)
    {
        var sb = new StringBuilder();
        sb.AppendLine($"{item.Source} / {item.Slug}");
        sb.AppendLine($"Cache key: {item.CacheKey}");
        sb.AppendLine($"Size: {FormatSize(item.ByteCount)}");
        sb.AppendLine($"Fetched: {FormatTimestamp(item.FetchedAt)}");
        sb.AppendLine($"Policy: {item.Policy}");
        if (!string.IsNullOrWhiteSpace(item.NextRefreshDue))
        {
            sb.AppendLine($"Next refresh due: {FormatTimestamp(item.NextRefreshDue)}");
        }
        sb.AppendLine($"Path: {item.Path}");
        sb.AppendLine();
        sb.AppendLine(JsonFormatter.Format(item.Raw));
        return sb.ToString();
    }

    private static string _sourceFromPath(string path)
    {
        var lower = path.Replace('\\', '/').ToLowerInvariant();
        if (lower.Contains("/devdocs/"))
        {
            return "devdocs";
        }
        if (lower.Contains("/mdn/"))
        {
            return "mdn";
        }
        if (lower.Contains("/dash/"))
        {
            return "dash";
        }
        if (lower.Contains("/catalogs/"))
        {
            return "catalog";
        }
        return "unknown";
    }

    private static string _slugFromCacheKey(string cacheKey, string path)
    {
        if (!string.IsNullOrWhiteSpace(cacheKey))
        {
            return cacheKey.Split('/', 2, StringSplitOptions.TrimEntries)[0];
        }

        var fileName = System.IO.Path.GetFileName(path);
        return fileName.Replace(".meta.json", "", StringComparison.OrdinalIgnoreCase);
    }

    private static string FormatTimestamp(string isoText)
    {
        if (string.IsNullOrWhiteSpace(isoText))
        {
            return "n/a";
        }
        return DateTimeOffset.TryParse(isoText, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var parsed)
            ? parsed.ToLocalTime().ToString("yyyy-MM-dd HH:mm")
            : isoText;
    }

    private static string FormatSize(long bytes)
    {
        var value = (double)bytes;
        string[] units = ["B", "KB", "MB", "GB"];
        var unitIndex = 0;
        while (value >= 1024 && unitIndex < units.Length - 1)
        {
            value /= 1024;
            unitIndex++;
        }
        return $"{value:0.#} {units[unitIndex]}";
    }
}
