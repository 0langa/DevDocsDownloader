using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class PresetsPage : Page
{
    private readonly Dictionary<string, List<string>> _presets = new(StringComparer.OrdinalIgnoreCase);
    private bool _initialized;

    public PresetsPage()
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
        await LoadPresetsAsync();
    }

    private async void OnLoadPresets(object sender, RoutedEventArgs e)
    {
        await LoadPresetsAsync();
    }

    private void OnPresetSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (PresetList.SelectedItem is not string preset || !_presets.TryGetValue(preset, out var languages))
        {
            AuditPresetButton.IsEnabled = false;
            UsePresetButton.IsEnabled = false;
            return;
        }
        App.MainViewModel.RecordPresetSelection(preset);
        PresetTitleText.Text = preset;
        PresetLanguagesText.Text = string.Join(", ", languages);
        AuditPresetButton.IsEnabled = true;
        UsePresetButton.IsEnabled = true;
    }

    private async void OnAuditSelectedPreset(object sender, RoutedEventArgs e)
    {
        if (PresetList.SelectedItem is not string preset)
        {
            return;
        }
        try
        {
            PresetTitleText.Text = $"Auditing {preset}...";
            var result = await App.BackendHost.Client.AuditPresetsAsync(new JsonObject
            {
                ["presets"] = new JsonArray(JsonValue.Create(preset)),
            });
            AuditResultsList.ItemsSource = (result ?? [])
                .OfType<JsonObject>()
                .Select(item =>
                {
                    var language = item["language"]?.GetValue<string>() ?? "";
                    var resolved = item["resolved"]?.GetValue<bool?>() == true ? "resolved" : "missing";
                    var source = item["source"]?.GetValue<string>() ?? "";
                    var slug = item["slug"]?.GetValue<string>() ?? "";
                    return $"{language} -> {resolved} {source} {slug}".Trim();
                })
                .ToList();
            PresetTitleText.Text = $"Audit results for {preset}";
        }
        catch (Exception exc)
        {
            PresetTitleText.Text = exc.Message;
        }
    }

    private void OnUsePresetInBulk(object sender, RoutedEventArgs e)
    {
        if (PresetList.SelectedItem is not string preset || !_presets.TryGetValue(preset, out var languages))
        {
            return;
        }
        var bulkPage = App.MainWindow.GetCachedPage<BulkPage>();
        if (bulkPage is null)
        {
            return;
        }
        foreach (var language in languages)
        {
            bulkPage.AddLanguage(language);
        }
        App.MainWindow.NavigateTo("BulkPage");
    }

    private async Task LoadPresetsAsync()
    {
        try
        {
            var result = await App.BackendHost.Client.GetPresetsAsync() as JsonObject;
            _presets.Clear();
            if (result is not null)
            {
                foreach (var pair in result)
                {
                    if (pair.Value is not JsonArray values)
                    {
                        continue;
                    }
                    _presets[pair.Key] = values.Select(item => item?.GetValue<string>() ?? "").Where(item => !string.IsNullOrWhiteSpace(item)).ToList();
                }
            }
            PresetList.ItemsSource = _presets.Keys.OrderBy(item => item).ToList();
            if (!string.IsNullOrWhiteSpace(App.MainViewModel.LastSelectedPreset) && _presets.ContainsKey(App.MainViewModel.LastSelectedPreset))
            {
                PresetList.SelectedItem = App.MainViewModel.LastSelectedPreset;
            }
            PresetTitleText.Text = "Select a preset.";
            PresetLanguagesText.Text = "";
            AuditResultsList.ItemsSource = null;
        }
        catch (Exception exc)
        {
            PresetTitleText.Text = exc.Message;
        }
    }
}
