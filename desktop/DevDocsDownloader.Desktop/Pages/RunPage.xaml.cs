using System.ComponentModel;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class RunPage : Page
{
    private bool _initialized;

    public RunPage()
    {
        InitializeComponent();
        App.MainViewModel.PropertyChanged += OnShellPropertyChanged;
        EventsList.ItemsSource = App.MainViewModel.ActivityLines;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
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
        }
        else
        {
            OutputRootText.Text = $"Output root: {App.MainViewModel.CurrentOutputRoot}";
            RefreshProgress();
        }
    }

    public void ApplySuggestedLanguage(string language, string source)
    {
        LanguageBox.Text = language;
        SetSourceSelection(source);
        ValidateForm();
    }

    private async void OnStartRun(object sender, RoutedEventArgs e)
    {
        try
        {
            var source = GetSelectedSource();
            var payload = new JsonObject
            {
                ["language"] = LanguageBox.Text.Trim(),
                ["mode"] = ModeBox.SelectedItem?.ToString() ?? "important",
                ["source"] = source,
                ["validate_only"] = ValidateOnlyBox.IsChecked == true,
                ["force_refresh"] = ForceRefreshBox.IsChecked == true,
            };
            var result = await App.BackendHost.Client.StartRunLanguageAsync(payload);
            var jobId = result?["id"]?.GetValue<string>() ?? "";
            var language = payload["language"]?.GetValue<string>() ?? "language";
            App.MainViewModel.DefaultMode = payload["mode"]?.GetValue<string>() ?? App.MainViewModel.DefaultMode;
            App.MainViewModel.SourcePreference = source ?? "";
            await App.MainViewModel.StartTrackingJobAsync(jobId, language, "run_language");
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
        SourceBox.Items.Add("Any (auto)");
        SourceBox.Items.Add("devdocs");
        SourceBox.Items.Add("mdn");
        SourceBox.Items.Add("dash");
        SetSourceSelection(App.MainViewModel.SourcePreference);
    }

    private void SetSourceSelection(string source)
    {
        var item = SourceBox.Items.Cast<object?>().FirstOrDefault(
            item => item?.ToString()?.Equals(source, StringComparison.OrdinalIgnoreCase) == true);
        SourceBox.SelectedItem = item ?? SourceBox.Items.FirstOrDefault();
    }

    private string? GetSelectedSource()
    {
        var selected = SourceBox.SelectedItem?.ToString();
        return selected == "Any (auto)" || string.IsNullOrWhiteSpace(selected) ? null : selected;
    }

    private void ValidateForm()
    {
        StartRunButton.IsEnabled = App.MainViewModel.BackendReady && !string.IsNullOrWhiteSpace(LanguageBox.Text);
    }
}
