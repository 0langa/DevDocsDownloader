using System.Diagnostics;
using System.Globalization;
using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class OutputBrowserPage : Page
{
    private sealed class BundleItem
    {
        public required string LanguageSlug { get; init; }
        public required string Language { get; init; }
        public required string Source { get; init; }
        public required string Path { get; init; }
        public int TotalDocuments { get; init; }
        public long BundleBytes { get; init; }
        public int FileCount { get; init; }
        public int ChunkCount { get; init; }
        public string GeneratedAt { get; init; } = "";

        public override string ToString() => $"{Language} ({Source}, {TotalDocuments} docs, {FormatBytes(BundleBytes)})";
    }

    private sealed class OutputNode
    {
        public required string Name { get; init; }
        public required string RelativePath { get; init; }
        public bool IsDir { get; init; }

        public override string ToString() => Name;
    }

    private readonly List<BundleItem> _bundles = [];
    private BundleItem? _selectedBundle;
    private bool _initialized;

    public OutputBrowserPage()
    {
        InitializeComponent();
        OutputRootText.Text = $"Output root: {App.MainViewModel.CurrentOutputRoot}";
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        OutputRootText.Text = $"Output root: {App.MainViewModel.CurrentOutputRoot}";
        if (_initialized)
        {
            return;
        }
        _initialized = true;
        await RefreshBundlesAsync();
    }

    public async Task FocusBundleAsync(string languageSlug)
    {
        await RefreshBundlesAsync(languageSlug);
    }

    public void UpdateOutputRoot()
    {
        OutputRootText.Text = $"Output root: {App.MainViewModel.CurrentOutputRoot}";
    }

    private async void OnRefreshBundles(object sender, RoutedEventArgs e)
    {
        await RefreshBundlesAsync();
    }

    private async void OnReloadTree(object sender, RoutedEventArgs e)
    {
        if (_selectedBundle is null)
        {
            return;
        }
        await LoadTreeAsync(_selectedBundle);
    }

    private void OnOpenOutputFolder(object sender, RoutedEventArgs e)
    {
        try
        {
            var target = _selectedBundle?.Path;
            if (string.IsNullOrWhiteSpace(target))
            {
                target = App.MainViewModel.CurrentOutputRoot;
            }
            if (string.IsNullOrWhiteSpace(target))
            {
                StatusText.Text = "No output folder configured.";
                return;
            }
            Process.Start(new ProcessStartInfo("explorer.exe", $"\"{target}\"") { UseShellExecute = true });
            StatusText.Text = $"Opened {target}";
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async void OnBundleSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (BundlesList.SelectedItem is not BundleItem bundle)
        {
            return;
        }
        _selectedBundle = bundle;
        RefreshTreeButton.IsEnabled = true;
        DeleteBundleButton.IsEnabled = true;
        BundleDetailText.Text = FormatBundleDetail(bundle);
        await LoadTreeAsync(bundle);
    }

    private async void OnTreeSelectionChanged(TreeView sender, TreeViewSelectionChangedEventArgs args)
    {
        if (_selectedBundle is null || sender.SelectedNode?.Content is not OutputNode node || node.IsDir)
        {
            return;
        }
        try
        {
            var result = await App.BackendHost.Client.GetOutputFileAsync(_selectedBundle.LanguageSlug, node.RelativePath);
            PreviewPathText.Text = $"{_selectedBundle.LanguageSlug}/{node.RelativePath}";
            PreviewBox.Text = result?["content"]?.GetValue<string>() ?? JsonFormatter.Format(result);
            App.MainViewModel.RecordOutputSelection(_selectedBundle.LanguageSlug, node.RelativePath);
        }
        catch (Exception exc)
        {
            PreviewBox.Text = exc.Message;
        }
    }

    private async Task RefreshBundlesAsync(string? preferredSlug = null)
    {
        try
        {
            StatusText.Text = "Loading bundles...";
            _bundles.Clear();
            var result = await App.BackendHost.Client.GetOutputBundlesAsync();
            foreach (var item in result ?? [])
            {
                if (item is not JsonObject row)
                {
                    continue;
                }
                _bundles.Add(new BundleItem
                {
                    LanguageSlug = row["language_slug"]?.GetValue<string>() ?? "",
                    Language = row["language"]?.GetValue<string>() ?? (row["language_slug"]?.GetValue<string>() ?? ""),
                    Source = row["source"]?.GetValue<string>() ?? "",
                    Path = row["path"]?.GetValue<string>() ?? "",
                    TotalDocuments = row["total_documents"]?.GetValue<int?>() ?? 0,
                    BundleBytes = row["bundle_bytes"]?.GetValue<long?>() ?? 0,
                    FileCount = row["file_count"]?.GetValue<int?>() ?? 0,
                    ChunkCount = row["chunk_count"]?.GetValue<int?>() ?? 0,
                    GeneratedAt = row["generated_at"]?.GetValue<string>() ?? "",
                });
            }
            BundlesList.ItemsSource = null;
            BundlesList.ItemsSource = _bundles.OrderBy(item => item.Language).ToList();
            RefreshTreeButton.IsEnabled = false;
            DeleteBundleButton.IsEnabled = false;
            BundleDetailText.Text = "";
            StatusText.Text = _bundles.Count == 0 ? "No output bundles found yet." : $"Loaded {_bundles.Count} bundles.";
            await RefreshStorageSummaryAsync();

            var targetSlug = preferredSlug
                ?? App.MainViewModel.LastOutputLanguageSlug
                ?? string.Empty;
            if (!string.IsNullOrWhiteSpace(targetSlug))
            {
                BundlesList.SelectedItem = _bundles.FirstOrDefault(item => item.LanguageSlug == targetSlug);
            }
            if (BundlesList.SelectedItem is null && _bundles.Count > 0)
            {
                BundlesList.SelectedIndex = 0;
            }
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async Task LoadTreeAsync(BundleItem bundle)
    {
        try
        {
            PreviewPathText.Text = $"{bundle.LanguageSlug}";
            PreviewBox.Text = "";
            FilesTree.RootNodes.Clear();
            var tree = await App.BackendHost.Client.GetOutputTreeAsync(bundle.LanguageSlug);
            if (tree is not JsonObject root)
            {
                StatusText.Text = "No tree data returned.";
                return;
            }
            FilesTree.RootNodes.Add(BuildTree(root));
            StatusText.Text = $"Loaded {bundle.Language} output tree.";
            if (!string.IsNullOrWhiteSpace(App.MainViewModel.LastOutputRelativePath))
            {
                PreviewPathText.Text = $"{bundle.LanguageSlug}/{App.MainViewModel.LastOutputRelativePath}";
            }
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async void OnDeleteBundle(object sender, RoutedEventArgs e)
    {
        if (_selectedBundle is null)
        {
            return;
        }
        var dialog = new ContentDialog
        {
            Title = "Delete output bundle?",
            Content =
                $"Delete {_selectedBundle.Language} from the output browser? This removes generated Markdown, chunks, and bundle metadata under that language folder.",
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
            var result = await App.BackendHost.Client.DeleteOutputBundleAsync(_selectedBundle.LanguageSlug);
            var freedBytes = result?["freed_bytes"]?.GetValue<long?>() ?? 0;
            StatusText.Text = $"Deleted {_selectedBundle.Language} ({FormatBytes(freedBytes)} freed).";
            PreviewPathText.Text = "";
            PreviewBox.Text = "";
            BundleDetailText.Text = "";
            FilesTree.RootNodes.Clear();
            await RefreshBundlesAsync();
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async void OnPruneReportHistory(object sender, RoutedEventArgs e)
    {
        var dialog = new ContentDialog
        {
            Title = "Prune report history?",
            Content = "Keep the latest 10 history reports and delete older report snapshots? Current bundles stay untouched.",
            PrimaryButtonText = "Prune",
            CloseButtonText = "Cancel",
            XamlRoot = XamlRoot,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }
        try
        {
            var result = await App.BackendHost.Client.PruneReportHistoryAsync();
            var deletedFiles = result?["deleted_files"]?.GetValue<int?>() ?? 0;
            var freedBytes = result?["freed_bytes"]?.GetValue<long?>() ?? 0;
            StatusText.Text = deletedFiles == 0
                ? "Report history already within retention target."
                : $"Pruned {deletedFiles} report snapshot(s) ({FormatBytes(freedBytes)} freed).";
            await RefreshStorageSummaryAsync();
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async Task RefreshStorageSummaryAsync()
    {
        try
        {
            var summary = await App.BackendHost.Client.GetOutputStorageSummaryAsync() as JsonObject;
            if (summary is null)
            {
                StorageSummaryText.Text = "";
                return;
            }
            var bundleCount = summary["bundle_count"]?.GetValue<int?>() ?? 0;
            var bundleBytes = summary["total_bundle_bytes"]?.GetValue<long?>() ?? 0;
            var reportBytes = (summary["latest_reports_bytes"]?.GetValue<long?>() ?? 0)
                + (summary["history_reports_bytes"]?.GetValue<long?>() ?? 0)
                + (summary["validation_records_bytes"]?.GetValue<long?>() ?? 0)
                + (summary["trends_bytes"]?.GetValue<long?>() ?? 0);
            var historyCount = summary["history_report_count"]?.GetValue<int?>() ?? 0;
            var totalManaged = summary["total_managed_bytes"]?.GetValue<long?>() ?? 0;
            StorageSummaryText.Text =
                $"Storage summary: {bundleCount} bundle(s), {FormatBytes(bundleBytes)} in bundles, {FormatBytes(reportBytes)} in reports, {historyCount} history snapshot(s), {FormatBytes(totalManaged)} total managed.";
        }
        catch (Exception exc)
        {
            StorageSummaryText.Text = exc.Message;
        }
    }

    private static string FormatBundleDetail(BundleItem bundle)
    {
        var generated = string.IsNullOrWhiteSpace(bundle.GeneratedAt) ? "unknown time" : bundle.GeneratedAt;
        return
            $"Bundle details: {bundle.TotalDocuments} docs, {bundle.FileCount} file(s), {bundle.ChunkCount} chunk(s), {FormatBytes(bundle.BundleBytes)}, generated {generated}.";
    }

    private static string FormatBytes(long bytes)
    {
        string[] units = ["B", "KB", "MB", "GB"];
        double value = bytes;
        var unitIndex = 0;
        while (value >= 1024 && unitIndex < units.Length - 1)
        {
            value /= 1024;
            unitIndex++;
        }
        return string.Format(CultureInfo.InvariantCulture, "{0:0.#} {1}", value, units[unitIndex]);
    }

    private static TreeViewNode BuildTree(JsonObject node)
    {
        var outputNode = new OutputNode
        {
            Name = node["name"]?.GetValue<string>() ?? ".",
            RelativePath = node["relative_path"]?.GetValue<string>() ?? ".",
            IsDir = node["is_dir"]?.GetValue<bool?>() ?? false,
        };
        var treeNode = new TreeViewNode { Content = outputNode, IsExpanded = outputNode.RelativePath is "." };
        if (node["children"] is JsonArray children)
        {
            foreach (var child in children.OfType<JsonObject>())
            {
                treeNode.Children.Add(BuildTree(child));
            }
        }
        return treeNode;
    }
}
