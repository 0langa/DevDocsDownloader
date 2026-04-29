using System.Net.Http.Headers;
using System.Net.Http.Json;
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

    public Task<JsonNode?> GetRuntimeSnapshotAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/runtime/snapshot", cancellationToken);

    public Task<JsonArray?> GetOutputBundlesAsync(CancellationToken cancellationToken = default) =>
        GetArrayAsync("/output/bundles", cancellationToken);

    public Task<JsonNode?> GetOutputTreeAsync(string languageSlug, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/output/{languageSlug}/tree", cancellationToken);

    public Task<JsonNode?> GetOutputMetaAsync(string languageSlug, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/output/{languageSlug}/meta", cancellationToken);

    public Task<JsonNode?> GetOutputFileAsync(string languageSlug, string path, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/output/{languageSlug}/file?path={Uri.EscapeDataString(path)}", cancellationToken);

    public Task<JsonNode?> GetReportsAsync(CancellationToken cancellationToken = default) =>
        GetJsonAsync("/reports", cancellationToken);

    public Task<JsonNode?> GetReportFileAsync(string path, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/reports/file?path={Uri.EscapeDataString(path)}", cancellationToken);

    public Task<JsonArray?> GetCheckpointsAsync(CancellationToken cancellationToken = default) =>
        GetArrayAsync("/checkpoints", cancellationToken);

    public Task<JsonNode?> GetCheckpointAsync(string slug, CancellationToken cancellationToken = default) =>
        GetJsonAsync($"/checkpoints/{slug}", cancellationToken);

    public Task<JsonNode?> DeleteCheckpointAsync(string slug, CancellationToken cancellationToken = default) =>
        DeleteJsonAsync($"/checkpoints/{slug}", cancellationToken);

    public Task<JsonArray?> GetCacheMetadataAsync(CancellationToken cancellationToken = default) =>
        GetArrayAsync("/cache/metadata", cancellationToken);

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
