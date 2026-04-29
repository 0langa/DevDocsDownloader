using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using CommunityToolkit.Mvvm.ComponentModel;
using DevDocsDownloader.Desktop.Services;

namespace DevDocsDownloader.Desktop.ViewModels;

public partial class MainWindowViewModel : ObservableObject
{
    private CancellationTokenSource? _jobMonitorCts;
    private Task? _jobMonitorTask;

    [ObservableProperty]
    private string _statusText = "Starting backend...";

    [ObservableProperty]
    private bool _backendReady;

    [ObservableProperty]
    private string _currentOutputRoot = "";

    [ObservableProperty]
    private string _cachePolicy = "use-if-present";

    [ObservableProperty]
    private int? _cacheTtlHours;

    [ObservableProperty]
    private string _defaultMode = "important";

    [ObservableProperty]
    private string _sourcePreference = "";

    [ObservableProperty]
    private string _languageTreeMode = "source";

    [ObservableProperty]
    private string _languageSearch = "";

    [ObservableProperty]
    private string _lastOutputLanguageSlug = "";

    [ObservableProperty]
    private string _lastOutputRelativePath = "";

    [ObservableProperty]
    private string _lastSelectedPreset = "";

    [ObservableProperty]
    private int _languageConcurrency = 3;

    [ObservableProperty]
    private string _bulkConcurrencyPolicy = "static";

    [ObservableProperty]
    private bool _emitDocumentFrontmatter;

    [ObservableProperty]
    private bool _emitChunks;

    [ObservableProperty]
    private string _activeJobId = "";

    [ObservableProperty]
    private string _activeJobLabel = "";

    [ObservableProperty]
    private string _activeJobKind = "";

    [ObservableProperty]
    private string _progressPhase = "";

    [ObservableProperty]
    private string _latestActivity = "";

    [ObservableProperty]
    private int _completedDocuments;

    [ObservableProperty]
    private int _totalDocuments;

    [ObservableProperty]
    private double _progressValue;

    [ObservableProperty]
    private bool _progressVisible;

    [ObservableProperty]
    private bool _progressIndeterminate = true;

    [ObservableProperty]
    private int _warningCount;

    [ObservableProperty]
    private int _failureCount;

    [ObservableProperty]
    private string _runtimeTelemetryText = "";

    [ObservableProperty]
    private string _lastErrorHint = "";

    public ObservableCollection<string> ActivityLines { get; } = [];

    public string BackendLogPath =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "DevDocsDownloader",
            "logs",
            "desktop-shell.log");

    public async Task InitializeAsync()
    {
        try
        {
            await App.BackendHost.StartAsync();
            BackendReady = true;
            StatusText = "Ready";
            await LoadSettingsAsync();
            await RecoverActiveJobAsync();
        }
        catch (Exception exc)
        {
            DesktopDiagnostics.Log("Backend startup failed during main window initialization.", exc);
            StatusText = $"Backend startup failed: {exc.Message}";
            LastErrorHint = $"See desktop log: {BackendLogPath}";
            BackendReady = false;
        }
    }

    public async Task LoadSettingsAsync()
    {
        if (!BackendReady)
        {
            return;
        }
        var settings = await App.BackendHost.Client.GetSettingsAsync() as JsonObject;
        ApplySettings(settings);
    }

    public async Task SaveSettingsAsync(JsonObject payload)
    {
        var saved = await App.BackendHost.Client.SaveSettingsAsync(payload) as JsonObject;
        ApplySettings(saved);
    }

    public async Task StartTrackingJobAsync(string jobId, string label, string kind)
    {
        CancelTracking();
        ResetProgress();
        ActiveJobId = jobId;
        ActiveJobLabel = label;
        ActiveJobKind = kind;
        ProgressVisible = true;
        LatestActivity = $"Starting {label}";
        AppendActivity(LatestActivity);
        _jobMonitorCts = new CancellationTokenSource();
        _jobMonitorTask = MonitorJobAsync(jobId, _jobMonitorCts.Token);
        await Task.CompletedTask;
    }

    public async Task CancelActiveJobAsync()
    {
        if (!BackendReady || string.IsNullOrWhiteSpace(ActiveJobId))
        {
            return;
        }
        try
        {
            await App.BackendHost.Client.CancelJobAsync(ActiveJobId);
            AppendActivity($"Cancellation requested for {ActiveJobLabel}.");
        }
        catch (Exception exc)
        {
            AppendActivity($"Cancel failed: {exc.Message}");
        }
    }

    public async Task RecoverActiveJobAsync()
    {
        if (!BackendReady)
        {
            return;
        }
        var jobs = await App.BackendHost.Client.GetJobsAsync();
        if (jobs is null)
        {
            return;
        }
        foreach (var node in jobs)
        {
            if (node is not JsonObject job)
            {
                continue;
            }
            var status = job["status"]?.GetValue<string>() ?? "";
            if (status is not ("running" or "pending"))
            {
                continue;
            }
            var id = job["id"]?.GetValue<string>() ?? "";
            if (string.IsNullOrWhiteSpace(id))
            {
                continue;
            }
            var language = job["language"]?.GetValue<string>() ?? "";
            var detail = job["detail"]?.GetValue<string>() ?? language;
            var kind = job["kind"]?.GetValue<string>() ?? "";
            await StartTrackingJobAsync(id, string.IsNullOrWhiteSpace(detail) ? "active job" : detail, kind);
            return;
        }
    }

    public void RecordLanguageSelection(string displayName, string source)
    {
        SourcePreference = source;
        AppendActivity($"Selected {displayName} from {source}.");
    }

    public void RecordOutputSelection(string languageSlug, string relativePath)
    {
        LastOutputLanguageSlug = languageSlug;
        LastOutputRelativePath = relativePath;
    }

    public void RecordPresetSelection(string preset)
    {
        LastSelectedPreset = preset;
    }

    private async Task MonitorJobAsync(string jobId, CancellationToken cancellationToken)
    {
        try
        {
            await SyncJobStatusAsync(jobId, cancellationToken);
            await foreach (var (eventName, payload) in App.BackendHost.Client.StreamJobEventsAsync(jobId, cancellationToken))
            {
                HandleJobEvent(eventName, payload);
            }
            await SyncJobStatusAsync(jobId, cancellationToken);
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception exc)
        {
            FailureCount += 1;
            LatestActivity = $"Live monitoring stopped: {exc.Message}";
            AppendActivity(LatestActivity);
            LastErrorHint = "Backend connection changed. You can still refresh data from each tab.";
        }
    }

    private async Task SyncJobStatusAsync(string jobId, CancellationToken cancellationToken)
    {
        var job = await App.BackendHost.Client.GetJobAsync(jobId, cancellationToken) as JsonObject;
        if (job is null)
        {
            return;
        }
        var status = job["status"]?.GetValue<string>() ?? "";
        var detail = job["detail"]?.GetValue<string>() ?? ActiveJobLabel;
        ActiveJobLabel = detail;
        if (status is "completed" or "failed" or "cancelled")
        {
            ProgressIndeterminate = false;
            ProgressVisible = true;
            ProgressValue = status == "completed" ? 100 : ProgressValue;
            LatestActivity = $"Job {status}: {detail}";
            AppendActivity(LatestActivity);
            if (status != "completed")
            {
                FailureCount += 1;
            }
            ActiveJobId = "";
        }
    }

    private void ApplySettings(JsonObject? settings)
    {
        if (settings is null)
        {
            return;
        }
        CurrentOutputRoot = settings["output_dir"]?.GetValue<string>() ?? CurrentOutputRoot;
        CachePolicy = settings["cache_policy"]?.GetValue<string>() ?? CachePolicy;
        CacheTtlHours = settings["cache_ttl_hours"]?.GetValue<int?>();
        DefaultMode = settings["default_mode"]?.GetValue<string>() ?? DefaultMode;
        SourcePreference = settings["source_preference"]?.GetValue<string>() ?? SourcePreference;
        LanguageTreeMode = settings["language_tree_mode"]?.GetValue<string>() ?? LanguageTreeMode;
        LanguageSearch = settings["language_search"]?.GetValue<string>() ?? LanguageSearch;
        LastOutputLanguageSlug = settings["last_output_language_slug"]?.GetValue<string>() ?? LastOutputLanguageSlug;
        LastOutputRelativePath = settings["last_output_relative_path"]?.GetValue<string>() ?? LastOutputRelativePath;
        LastSelectedPreset = settings["last_selected_preset"]?.GetValue<string>() ?? LastSelectedPreset;
        LanguageConcurrency = settings["language_concurrency"]?.GetValue<int?>() ?? LanguageConcurrency;
        BulkConcurrencyPolicy = settings["bulk_concurrency_policy"]?.GetValue<string>() ?? BulkConcurrencyPolicy;
        EmitDocumentFrontmatter = settings["emit_document_frontmatter"]?.GetValue<bool?>() ?? EmitDocumentFrontmatter;
        EmitChunks = settings["emit_chunks"]?.GetValue<bool?>() ?? EmitChunks;
    }

    private void HandleJobEvent(string eventName, JsonObject payload)
    {
        if (eventName == "complete")
        {
            ProgressIndeterminate = false;
            if (ProgressValue <= 0)
            {
                ProgressValue = 100;
            }
            return;
        }

        var eventType = payload["event_type"]?.GetValue<string>() ?? eventName;
        switch (eventType)
        {
            case "phase_change":
                ProgressPhase = payload["phase"]?.GetValue<string>() ?? "";
                LatestActivity = payload["message"]?.GetValue<string>() ?? ProgressPhase;
                ProgressVisible = true;
                if (ProgressPhase is "fetching")
                {
                    ProgressIndeterminate = true;
                }
                if (ProgressPhase is "validating")
                {
                    ProgressIndeterminate = false;
                    ProgressValue = Math.Max(ProgressValue, 90);
                }
                if (!string.IsNullOrWhiteSpace(LatestActivity))
                {
                    AppendActivity(LatestActivity);
                }
                break;
            case "activity":
                LatestActivity = payload["message"]?.GetValue<string>() ?? "";
                if (!string.IsNullOrWhiteSpace(LatestActivity))
                {
                    AppendActivity(LatestActivity);
                }
                break;
            case "document_emitted":
                ProgressVisible = true;
                ProgressIndeterminate = false;
                var eventPayload = payload["payload"] as JsonObject;
                CompletedDocuments = eventPayload?["index"]?.GetValue<int?>() ?? (CompletedDocuments + 1);
                TotalDocuments = eventPayload?["total"]?.GetValue<int?>() ?? TotalDocuments;
                var title = eventPayload?["title"]?.GetValue<string>() ?? "";
                var topic = eventPayload?["topic"]?.GetValue<string>() ?? "";
                LatestActivity = string.IsNullOrWhiteSpace(title) ? "Formatted document." : $"Formatted {title}";
                ProgressValue = TotalDocuments > 0
                    ? Math.Min(89, (double)CompletedDocuments / TotalDocuments * 85)
                    : Math.Min(89, CompletedDocuments);
                AppendActivity(string.IsNullOrWhiteSpace(topic) ? LatestActivity : $"{LatestActivity} ({topic})");
                break;
            case "warning":
                WarningCount += 1;
                LatestActivity = payload["message"]?.GetValue<string>() ?? "Warning";
                AppendActivity($"Warning: {LatestActivity}");
                break;
            case "runtime_telemetry":
                RuntimeTelemetryText = JsonFormatter.Format(payload["payload"]);
                break;
            case "validation_completed":
                ProgressVisible = true;
                ProgressIndeterminate = false;
                ProgressValue = 100;
                var score = (payload["payload"] as JsonObject)?["score"]?.GetValue<double?>() ?? 0;
                LatestActivity = $"Validation complete. Score {score:0.00}.";
                AppendActivity(LatestActivity);
                break;
            case "failure":
                FailureCount += 1;
                ProgressVisible = true;
                ProgressIndeterminate = false;
                LatestActivity = payload["message"]?.GetValue<string>() ?? "Job failed.";
                AppendActivity($"Failure: {LatestActivity}");
                break;
        }
    }

    private void ResetProgress()
    {
        ProgressPhase = "";
        LatestActivity = "";
        CompletedDocuments = 0;
        TotalDocuments = 0;
        ProgressValue = 0;
        ProgressVisible = false;
        ProgressIndeterminate = true;
        WarningCount = 0;
        FailureCount = 0;
        RuntimeTelemetryText = "";
        ActivityLines.Clear();
    }

    private void CancelTracking()
    {
        if (_jobMonitorCts is null)
        {
            return;
        }
        _jobMonitorCts.Cancel();
        _jobMonitorCts.Dispose();
        _jobMonitorCts = null;
        _jobMonitorTask = null;
    }

    private void AppendActivity(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return;
        }
        ActivityLines.Add($"[{DateTime.Now:HH:mm:ss}] {text}");
        while (ActivityLines.Count > 200)
        {
            ActivityLines.RemoveAt(0);
        }
    }
}
