using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class SettingsPage : Page
{
    private bool _initialized;

    public SettingsPage()
    {
        InitializeComponent();
        HelpBox.Text = """
            DevDocsDownloader 1.1.5 desktop shell

            What this app does
            - Download official documentation from DevDocs, MDN, and Dash-backed catalogs.
            - Compile the result into normalized Markdown under the selected output root.
            - Keep restart-safe checkpoints, reports, and cache metadata for recurring runs.

            Normal workflow
            1. Use Languages to browse the available catalog and send a language into Run or Bulk.
            2. Use Run for one language, or Bulk for comma-separated lists and preset-sized batches.
            3. Watch the live progress panel while the job fetches, formats, validates, and writes output.
            4. After completion, inspect Reports, Output Browser, Checkpoints, and Cache.

            Expected behavior
            - Tabs keep their state when you move around the shell.
            - Desktop jobs queue automatically; new runs show queued position instead of failing.
            - If startup fails, the sidebar shows the backend failure and the desktop log path.
            - Checkpoints are safe resume boundaries, not final output.

            Output layout
            - Markdown files are written under <output root>/markdown
            - Reports are written under <output root>/reports
            - Desktop cache, state, and logs stay under LocalAppData/DevDocsDownloader

            Cache and refresh
            - use-if-present: fast default
            - ttl: refresh after configured age
            - always-refresh: re-fetch every time
            - validate-if-possible: reuse cache but revalidate where the source supports it

            Non-technical guidance
            - Start with important mode unless you know you need the full catalog.
            - Use Refresh catalogs or force refresh only when source data seems stale.
            - If a run fails, check Reports and Checkpoints before retrying.
            """;
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (_initialized)
        {
            return;
        }
        _initialized = true;
        await LoadSettingsAsync();
    }

    private async void OnLoadSettings(object sender, RoutedEventArgs e)
    {
        await LoadSettingsAsync();
    }

    private async void OnChooseFolder(object sender, RoutedEventArgs e)
    {
        var path = await FolderPickerService.PickFolderAsync(App.MainWindow, OutputDirBox.Text);
        if (!string.IsNullOrWhiteSpace(path))
        {
            OutputDirBox.Text = path;
        }
    }

    private async void OnSaveSettings(object sender, RoutedEventArgs e)
    {
        try
        {
            var previousOutputRoot = App.MainViewModel.CurrentOutputRoot;
            await App.MainViewModel.SaveSettingsAsync(new JsonObject
            {
                ["output_dir"] = string.IsNullOrWhiteSpace(OutputDirBox.Text) ? null : OutputDirBox.Text,
                ["default_mode"] = ModeBox.SelectedItem?.ToString() ?? "important",
                ["source_preference"] = string.IsNullOrWhiteSpace(SourcePreferenceBox.Text) ? null : SourcePreferenceBox.Text,
                ["cache_policy"] = CachePolicyBox.SelectedItem?.ToString() ?? "use-if-present",
                ["cache_ttl_hours"] = int.TryParse(CacheTtlBox.Text, out var ttl) ? ttl : null,
                ["max_cache_size_mb"] = int.TryParse(MaxCacheSizeBox.Text, out var maxCacheSize) ? maxCacheSize : 2048,
                ["language_tree_mode"] = App.MainViewModel.LanguageTreeMode,
                ["language_search"] = App.MainViewModel.LanguageSearch,
                ["last_output_language_slug"] = App.MainViewModel.LastOutputLanguageSlug,
                ["last_output_relative_path"] = App.MainViewModel.LastOutputRelativePath,
                ["last_selected_preset"] = App.MainViewModel.LastSelectedPreset,
                ["language_concurrency"] = App.MainViewModel.LanguageConcurrency,
                ["bulk_concurrency_policy"] = App.MainViewModel.BulkConcurrencyPolicy,
                ["emit_document_frontmatter"] = App.MainViewModel.EmitDocumentFrontmatter,
                ["emit_chunks"] = App.MainViewModel.EmitChunks,
            });
            App.MainWindow.GetCachedPage<OutputBrowserPage>()?.UpdateOutputRoot();
            var outputChanged = !string.Equals(previousOutputRoot, App.MainViewModel.CurrentOutputRoot, StringComparison.OrdinalIgnoreCase);
            StatusText.Text = outputChanged
                ? $"Settings saved. Applies to next run. Output root changed to {App.MainViewModel.CurrentOutputRoot}. Existing output was not moved."
                : $"Settings saved. Applies to next run. Output root: {App.MainViewModel.CurrentOutputRoot}";
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }

    private async Task LoadSettingsAsync()
    {
        try
        {
            await App.MainViewModel.LoadSettingsAsync();
            OutputDirBox.Text = App.MainViewModel.CurrentOutputRoot;
            ModeBox.SelectedItem = App.MainViewModel.DefaultMode;
            SourcePreferenceBox.Text = App.MainViewModel.SourcePreference;
            CachePolicyBox.SelectedItem = App.MainViewModel.CachePolicy;
            CacheTtlBox.Text = App.MainViewModel.CacheTtlHours?.ToString() ?? "";
            MaxCacheSizeBox.Text = App.MainViewModel.MaxCacheSizeMb.ToString();
            StatusText.Text = $"Loaded settings from desktop backend. Log path: {App.MainViewModel.BackendLogPath}";
        }
        catch (Exception exc)
        {
            StatusText.Text = exc.Message;
        }
    }
}
