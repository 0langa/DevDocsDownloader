using System.Text.Json;
using System.Text.Json.Nodes;

namespace DevDocsDownloader.Desktop.Services;

public static class JsonFormatter
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    public static string Format(JsonNode? node)
    {
        return node?.ToJsonString(Options) ?? string.Empty;
    }
}
