using System.ComponentModel;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class BulkPage : Page
{
    private bool _initialized;

    public BulkPage()
    {
        InitializeComponent();
        App.MainViewModel.PropertyChanged += OnShellPropertyChanged;
        EventsList.ItemsSource = App.MainViewModel.ActivityLines;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (_initialized)
        {
            RefreshProgress();
            return;
        }
        _initialized = true;
        ModeBox.SelectedItem = App.MainViewModel.DefaultMode;
        ConcurrencyBox.Text = App.MainViewModel.LanguageConcurrency.ToString();
        PolicyBox.SelectedItem = App.MainViewModel.BulkConcurrencyPolicy;
        RefreshProgress();
        ValidateForm();
    }

    public void AddLanguage(string language)
    {
        var existing = LanguagesBox.Text.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToList();
        if (!existing.Contains(language, StringComparer.OrdinalIgnoreCase))
        {
            existing.Add(language);
        }
        LanguagesBox.Text = string.Join(", ", existing);
        ValidateForm();
    }

    private async void OnStartBulk(object sender, RoutedEventArgs e)
    {
        try
        {
            var languages = LanguagesBox.Text.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            var payload = new JsonObject
            {
                ["languages"] = new JsonArray(languages.Select(item => JsonValue.Create(item)).ToArray()),
                ["mode"] = ModeBox.SelectedItem?.ToString() ?? "important",
                ["language_concurrency"] = int.TryParse(ConcurrencyBox.Text, out var concurrency) ? concurrency : 3,
                ["concurrency_policy"] = PolicyBox.SelectedItem?.ToString() ?? "static",
            };
            var result = await App.BackendHost.Client.StartBulkAsync(payload);
            var jobId = result?["id"]?.GetValue<string>() ?? "";
            App.MainViewModel.LanguageConcurrency = int.TryParse(ConcurrencyBox.Text, out var parsed) ? parsed : App.MainViewModel.LanguageConcurrency;
            App.MainViewModel.BulkConcurrencyPolicy = payload["concurrency_policy"]?.GetValue<string>() ?? App.MainViewModel.BulkConcurrencyPolicy;
            await App.MainViewModel.StartTrackingJobAsync(jobId, $"{languages.Length} language(s)", "run_bulk");
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
    }

    private void ValidateForm()
    {
        StartBulkButton.IsEnabled = App.MainViewModel.BackendReady && !string.IsNullOrWhiteSpace(LanguagesBox.Text);
    }
}
