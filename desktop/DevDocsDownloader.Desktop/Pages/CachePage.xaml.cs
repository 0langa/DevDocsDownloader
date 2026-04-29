using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class CachePage : Page
{
    private sealed class CacheItem
    {
        public required string Source { get; init; }
        public required string CacheKey { get; init; }
        public required string FetchedAt { get; init; }
        public required string Policy { get; init; }
        public required JsonObject Raw { get; init; }

        public override string ToString() => $"{Source} - {CacheKey}";
    }

    private List<CacheItem> _items = [];
    private bool _initialized;

    public CachePage()
    {
        InitializeComponent();
        SortBox.SelectedIndex = 0;
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
        RenderItems();
    }

    private void OnSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CacheList.SelectedItem is not CacheItem item)
        {
            return;
        }
        DetailTitleText.Text = $"{item.Source} / {item.CacheKey}";
        ContentBox.Text = JsonFormatter.Format(item.Raw);
    }

    private async Task RefreshAsync()
    {
        try
        {
            var result = await App.BackendHost.Client.GetCacheMetadataAsync();
            _items = (result ?? [])
                .OfType<JsonObject>()
                .Select(item => new CacheItem
                {
                    Source = item["source"]?.GetValue<string>() ?? "",
                    CacheKey = item["cache_key"]?.GetValue<string>() ?? "",
                    FetchedAt = item["fetched_at"]?.GetValue<string>() ?? "",
                    Policy = item["policy"]?.GetValue<string>() ?? "",
                    Raw = item,
                })
                .ToList();
            RenderItems();
        }
        catch (Exception exc)
        {
            DetailTitleText.Text = exc.Message;
        }
    }

    private void RenderItems()
    {
        IEnumerable<CacheItem> ordered = _items;
        ordered = SortBox.SelectedIndex switch
        {
            1 => ordered.OrderByDescending(item => item.FetchedAt),
            2 => ordered.OrderBy(item => item.Policy).ThenBy(item => item.Source),
            _ => ordered.OrderBy(item => item.Source).ThenBy(item => item.CacheKey),
        };
        CacheList.ItemsSource = ordered.ToList();
        if (!ordered.Any())
        {
            DetailTitleText.Text = "No cache metadata found.";
            ContentBox.Text = "";
        }
    }
}
