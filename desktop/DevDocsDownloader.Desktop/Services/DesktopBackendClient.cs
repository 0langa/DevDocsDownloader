using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace DevDocsDownloader.Desktop.Services;

public sealed class DesktopBackendClient
{
    private readonly HttpClient _httpClient;
    private readonly JsonSerializerOptions _jsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    public DesktopBackendClient(HttpClient httpClient, string token)
    {
        _httpClient = httpClient;
        _httpClient.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
    }

    public Task<JsonNode?> GetHealthAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/health", cancellationToken);

    public Task<JsonNode?> GetVersionAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/version", cancellationToken);

    public Task<JsonArray?> GetLanguagesAsync(CancellationToken cancellationToken = default) =>
        GetArrayAsync("/languages", cancellationToken);

    public Task<JsonNode?> GetPresetsAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/presets", cancellationToken);

    public Task<JsonArray?> AuditPresetsAsync(JsonObject payload, CancellationToken cancellationToken = default) =>
        PostArrayAsync("/audit-presets", payload, cancellationToken);

    public Task<JsonNode?> RefreshCatalogsAsync(CancellationToken cancellationToken = default) =>
        PostJsonAsync("/refresh-catalogs", null, cancellationToken);

    public Task<JsonNode?> GetSettingsAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/settings", cancellationToken);

    public Task<JsonNode?> SaveSettingsAsync(JsonObject payload, CancellationToken cancellationToken = default) =>
        PutJsonAsync("/settings", payload, cancellationToken);

    public Task<JsonNode?> StartRunLanguageAsync(JsonObject payload, CancellationToken cancellationToken = default) =>
        PostJsonAsync("/jobs/run-language", payload, cancellationToken);

    public Task<JsonNode?> StartBulkAsync(JsonObject payload, CancellationToken cancellationToken = default) =>
        PostJsonAsync("/jobs/run-bulk", payload, cancellationToken);

    public Task<JsonNode?> StartValidateAsync(JsonObject payload, CancellationToken cancellationToken = default) =>
        PostJsonAsync("/jobs/validate", payload, cancellationToken);

    public Task<JsonArray?> GetJobsAsync(CancellationToken cancellationToken = default) =>
        GetArrayAsync("/jobs", cancellationToken);

    public Task<JsonNode?> GetJobQueueAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/jobs/queue", cancellationToken);

    public Task<JsonNode?> GetJobAsync(string jobId, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/jobs/{jobId}", cancellationToken);

    public Task<JsonNode?> CancelJobAsync(string jobId, CancellationToken cancellationToken = default) =>
        PostJsonAsync($"/jobs/{jobId}/cancel", null, cancellationToken);

    public async Task<IReadOnlyList<string>> GetJobEventsAsync(string jobId, CancellationToken cancellationToken = default)
    {
        using var response = await _httpClient.GetAsync($"/jobs/{jobId}/events", cancellationToken);
        response.EnsureSuccessStatusCode();
        var text = await response.Content.ReadAsStringAsync(cancellationToken);
        return text.Split("\n\n", StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    }

    public async IAsyncEnumerable<(string EventName, JsonObject Payload)> StreamJobEventsAsync(
        string jobId,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        // fromIndex tracks how many events we've received; used to resume after reconnect.
        int fromIndex = 0;
        int retries = 0;
        const int maxRetries = 5;

        while (!cancellationToken.IsCancellationRequested)
        {
            // --- Connect ---
            HttpResponseMessage? response = null;
            StreamReader? reader = null;
            bool connectFailed = false;
            bool connectCancelled = false;
            try
            {
                var request = new HttpRequestMessage(HttpMethod.Get, $"/jobs/{jobId}/events?from_index={fromIndex}");
                response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
                request.Dispose();
                if (!response.IsSuccessStatusCode)
                {
                    var error = await response.Content.ReadAsStringAsync(cancellationToken);
                    throw new InvalidOperationException($"Backend returned {(int)response.StatusCode}: {error}");
                }
                var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
                reader = new StreamReader(stream);
            }
            catch (OperationCanceledException)
            {
                connectCancelled = true;
                response?.Dispose();
            }
            catch (Exception exc)
            {
                connectFailed = true;
                response?.Dispose();
                DesktopDiagnostics.Log($"SSE connect failed for job {jobId} (attempt {retries + 1}): {exc.Message}");
            }

            if (connectCancelled)
            {
                yield break;
            }
            if (connectFailed)
            {
                if (++retries > maxRetries)
                {
                    yield break;
                }
                var backoff = TimeSpan.FromSeconds(Math.Min(retries * 2, 10));
                await Task.Delay(backoff, cancellationToken);
                continue;
            }

            // --- Read stream ---
            string currentEvent = "message";
            var dataBuilder = new StringBuilder();
            bool completedNormally = false;
            bool streamDone = false;

            while (!streamDone && !cancellationToken.IsCancellationRequested)
            {
                string? line = null;
                bool readCancelled = false;
                bool readFailed = false;
                try
                {
                    line = await reader!.ReadLineAsync(cancellationToken);
                }
                catch (OperationCanceledException)
                {
                    readCancelled = true;
                }
                catch
                {
                    readFailed = true;
                }

                if (readCancelled)
                {
                    streamDone = true;
                    connectCancelled = true;
                    break;
                }
                if (readFailed || line is null)
                {
                    streamDone = true;
                    break;
                }

                if (line.Length == 0)
                {
                    if (dataBuilder.Length > 0)
                    {
                        var payload = JsonNode.Parse(dataBuilder.ToString()) as JsonObject ?? new JsonObject();
                        dataBuilder.Clear();
                        fromIndex++;
                        retries = 0;
                        bool isComplete = string.Equals(currentEvent, "complete", StringComparison.Ordinal);
                        string evtName = currentEvent;
                        currentEvent = "message";
                        yield return (evtName, payload);
                        if (isComplete)
                        {
                            completedNormally = true;
                            streamDone = true;
                        }
                    }
                    continue;
                }

                if (line.StartsWith("event:", StringComparison.OrdinalIgnoreCase))
                {
                    currentEvent = line["event:".Length..].Trim();
                }
                else if (line.StartsWith("data:", StringComparison.OrdinalIgnoreCase))
                {
                    if (dataBuilder.Length > 0)
                    {
                        dataBuilder.AppendLine();
                    }
                    dataBuilder.Append(line["data:".Length..].Trim());
                }
                // keep-alive lines (":" prefix) are silently ignored
            }

            reader?.Dispose();
            response?.Dispose();

            if (connectCancelled || completedNormally)
            {
                yield break;
            }

            // Unexpected disconnect — reconnect with backoff
            if (++retries > maxRetries)
            {
                yield break;
            }
            var delay = TimeSpan.FromSeconds(Math.Min(retries * 2, 10));
            DesktopDiagnostics.Log($"SSE for job {jobId} disconnected; reconnecting (attempt {retries}/{maxRetries}) in {delay.TotalSeconds}s from event index {fromIndex}.");
            await Task.Delay(delay, cancellationToken);
        }
    }

    public Task<JsonNode?> GetRuntimeSnapshotAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/runtime/snapshot", cancellationToken);

    public Task<JsonArray?> GetOutputBundlesAsync(CancellationToken cancellationToken = default) =>
        GetArrayAsync("/output/bundles", cancellationToken);

    public Task<JsonNode?> GetOutputStorageSummaryAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/output/storage-summary", cancellationToken);

    public Task<JsonNode?> GetOutputTreeAsync(string languageSlug, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/output/{languageSlug}/tree", cancellationToken);

    public Task<JsonNode?> GetOutputMetaAsync(string languageSlug, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/output/{languageSlug}/meta", cancellationToken);

    public Task<JsonNode?> GetOutputFileAsync(string languageSlug, string path, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/output/{languageSlug}/file?path={Uri.EscapeDataString(path)}", cancellationToken);

    public Task<JsonNode?> DeleteOutputBundleAsync(string languageSlug, CancellationToken cancellationToken = default) =>
        DeleteJsonAsync($"/output/{languageSlug}", cancellationToken);

    public Task<JsonNode?> GetReportsAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/reports", cancellationToken);

    public Task<JsonNode?> GetReportFileAsync(string path, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/reports/file?path={Uri.EscapeDataString(path)}", cancellationToken);

    public Task<JsonNode?> PruneReportHistoryAsync(int keepLatest = 10, CancellationToken cancellationToken = default) =>
        PostJsonAsync($"/reports/prune-history?keep_latest={keepLatest}", null, cancellationToken);

    public Task<JsonArray?> GetCheckpointsAsync(CancellationToken cancellationToken = default) =>
        GetArrayAsync("/checkpoints", cancellationToken);

    public Task<JsonNode?> GetCheckpointAsync(string slug, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/checkpoints/{slug}", cancellationToken);

    public Task<JsonNode?> DeleteCheckpointAsync(string slug, CancellationToken cancellationToken = default) =>
        DeleteJsonAsync($"/checkpoints/{slug}", cancellationToken);

    public Task<JsonNode?> DeleteStaleCheckpointsAsync(CancellationToken cancellationToken = default) =>
        DeleteJsonAsync("/checkpoints/stale", cancellationToken);

    public Task<JsonArray?> GetCacheMetadataAsync(CancellationToken cancellationToken = default) =>
        GetArrayAsync("/cache/metadata", cancellationToken);

    public Task<JsonNode?> GetCacheSummaryAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/cache/summary", cancellationToken);

    public Task<JsonNode?> RefreshCacheEntryAsync(string source, string slug, CancellationToken cancellationToken = default) =>
        PostJsonAsync($"/cache/entry/refresh?source={Uri.EscapeDataString(source)}&slug={Uri.EscapeDataString(slug)}", null, cancellationToken);

    public Task<JsonNode?> DeleteCacheEntryAsync(string source, string slug, CancellationToken cancellationToken = default) =>
        DeleteJsonAsync($"/cache/entry?source={Uri.EscapeDataString(source)}&slug={Uri.EscapeDataString(slug)}", cancellationToken);

    public Task<JsonNode?> ClearSourceCacheAsync(string source, CancellationToken cancellationToken = default) =>
        DeleteJsonAsync($"/cache/source/{Uri.EscapeDataString(source)}", cancellationToken);

    public Task<JsonNode?> ClearAllCacheAsync(CancellationToken cancellationToken = default) =>
        DeleteJsonAsync("/cache", cancellationToken);

    private async Task<JsonNode?> GetJsonAsync(string path, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.GetAsync(path, cancellationToken);
        return await ParseJsonResponseAsync(response, cancellationToken);
    }

    private async Task<JsonArray?> GetArrayAsync(string path, CancellationToken cancellationToken)
    {
        var node = await GetJsonAsync(path, cancellationToken);
        return node as JsonArray;
    }

    private async Task<JsonNode?> PostJsonAsync(string path, JsonNode? payload, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsync(path, Serialize(payload), cancellationToken);
        return await ParseJsonResponseAsync(response, cancellationToken);
    }

    private async Task<JsonArray?> PostArrayAsync(string path, JsonNode? payload, CancellationToken cancellationToken)
    {
        var node = await PostJsonAsync(path, payload, cancellationToken);
        return node as JsonArray;
    }

    private async Task<JsonNode?> PutJsonAsync(string path, JsonNode? payload, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PutAsync(path, Serialize(payload), cancellationToken);
        return await ParseJsonResponseAsync(response, cancellationToken);
    }

    private async Task<JsonNode?> DeleteJsonAsync(string path, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.DeleteAsync(path, cancellationToken);
        return await ParseJsonResponseAsync(response, cancellationToken);
    }

    private async Task<JsonNode?> ParseJsonResponseAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var content = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"Backend request failed ({(int)response.StatusCode}): {content}");
        }
        return string.IsNullOrWhiteSpace(content) ? null : JsonNode.Parse(content);
    }

    private StringContent Serialize(JsonNode? payload)
    {
        var text = payload?.ToJsonString(_jsonOptions) ?? "{}";
        return new StringContent(text, Encoding.UTF8, "application/json");
    }
}
