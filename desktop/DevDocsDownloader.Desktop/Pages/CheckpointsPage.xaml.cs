using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class CheckpointsPage : Page
{
    private sealed class CheckpointItem
    {
        public required string Slug { get; init; }
        public required string Language { get; init; }
        public required string Source { get; init; }
        public required string Phase { get; init; }
        public required string SecondaryText { get; init; }
        public required bool IsStale { get; init; }
        public required string StaleReason { get; init; }

        public string PrimaryText => Language;
        public string StaleBadgeText => IsStale ? "STALE" : "";
        public double StaleBadgeOpacity => IsStale ? 1 : 0;
    }

    private readonly Dictionary<string, JsonObject> _details = [];
    private bool _initialized;

    public CheckpointsPage()
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

    private async void OnList(object sender, RoutedEventArgs e)
    {
        await RefreshAsync();
    }

    private async void OnSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CheckpointList.SelectedItem is not CheckpointItem item)
        {
            return;
        }
        UseCheckpointButton.IsEnabled = true;
        DeleteCheckpointButton.IsEnabled = true;
        try
        {
            var detail = await App.BackendHost.Client.GetCheckpointAsync(item.Slug) as JsonObject;
            if (detail is not null)
            {
                _details[item.Slug] = detail;
            }
            DetailTitleText.Text = item.IsStale ? $"{item.Language} checkpoint (stale)" : $"{item.Language} checkpoint";
            ContentBox.Text = JsonFormatter.Format(detail);
            if (item.IsStale && !string.IsNullOrWhiteSpace(item.StaleReason))
            {
                ContentBox.Text = $"Stale reason: {item.StaleReason}\n\n{ContentBox.Text}";
            }
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }

    private void OnUseCheckpoint(object sender, RoutedEventArgs e)
    {
        if (CheckpointList.SelectedItem is not CheckpointItem item)
        {
            return;
        }
        var runPage = App.MainWindow.GetCachedPage<RunPage>();
        runPage?.ApplySuggestedLanguage(item.Language, item.Source);
        App.MainWindow.NavigateTo("RunPage");
    }

    private async void OnDelete(object sender, RoutedEventArgs e)
    {
        if (CheckpointList.SelectedItem is not CheckpointItem item)
        {
            return;
        }
        var dialog = new ContentDialog
        {
            Title = "Delete checkpoint?",
            Content = $"Delete checkpoint for {item.Language}? This removes the saved resume boundary.",
            PrimaryButtonText = "Delete",
            CloseButtonText = "Cancel",
            XamlRoot = XamlRoot,
        };
        var result = await dialog.ShowAsync();
        if (result != ContentDialogResult.Primary)
        {
            return;
        }
        try
        {
            await App.BackendHost.Client.DeleteCheckpointAsync(item.Slug);
            await RefreshAsync();
            ContentBox.Text = $"{item.Language} checkpoint deleted.";
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }

    private async void OnDeleteStale(object sender, RoutedEventArgs e)
    {
        var staleItems = (CheckpointList.ItemsSource as IEnumerable<CheckpointItem>)?.Where(item => item.IsStale).ToList() ?? [];
        if (staleItems.Count == 0)
        {
            ContentBox.Text = "No stale checkpoints found.";
            return;
        }
        var dialog = new ContentDialog
        {
            Title = "Delete stale checkpoints?",
            Content = $"Delete {staleItems.Count} stale checkpoint(s)? This also removes their saved run state files.",
            PrimaryButtonText = "Delete stale",
            CloseButtonText = "Cancel",
            XamlRoot = XamlRoot,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }
        try
        {
            var result = await App.BackendHost.Client.DeleteStaleCheckpointsAsync() as JsonObject;
            var deleted = result?["deleted"]?.GetValue<int>() ?? 0;
            await RefreshAsync();
            ContentBox.Text = $"Deleted {deleted} stale checkpoint(s).";
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
            var result = await App.BackendHost.Client.GetCheckpointsAsync();
            var items = (result ?? [])
                .OfType<JsonObject>()
                .Select(item => new CheckpointItem
                {
                    Slug = item["slug"]?.GetValue<string>() ?? "",
                    Language = item["language"]?.GetValue<string>() ?? "",
                    Source = item["source"]?.GetValue<string>() ?? "",
                    Phase = item["phase"]?.GetValue<string>() ?? "",
                    SecondaryText =
                        $"{item["source"]?.GetValue<string>() ?? ""} • {item["phase"]?.GetValue<string>() ?? ""} • emitted {item["emitted_document_count"]?.GetValue<int>() ?? 0}",
                    IsStale = item["is_stale"]?.GetValue<bool>() ?? false,
                    StaleReason = item["stale_reason"]?.GetValue<string>() ?? "",
                })
                .OrderBy(item => item.Language)
                .ToList();
            CheckpointList.ItemsSource = items;
            DeleteStaleButton.IsEnabled = items.Any(item => item.IsStale);
            UseCheckpointButton.IsEnabled = false;
            DeleteCheckpointButton.IsEnabled = false;
            DetailTitleText.Text = items.Count == 0 ? "No active checkpoints." : "Select a checkpoint.";
            if (items.Count == 0)
            {
                ContentBox.Text = "";
            }
        }
        catch (Exception exc)
        {
            DetailTitleText.Text = exc.Message;
            DeleteStaleButton.IsEnabled = false;
        }
    }
}
