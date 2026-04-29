using System.Diagnostics;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace DevDocsDownloader.Desktop.Services;

public sealed class BackendProcessHost : IAsyncDisposable
{
    private Process? _process;
    private DesktopBackendClient? _client;

    public DesktopBackendClient Client => _client ?? throw new InvalidOperationException("Backend is not started.");
    public string Token { get; private set; } = string.Empty;
    public int Port { get; private set; }

    public async Task<DesktopBackendClient> StartAsync(CancellationToken cancellationToken = default)
    {
        if (_client is not null)
        {
            return _client;
        }

        Port = ReservePort();
        Token = Convert.ToHexString(RandomNumberGenerator.GetBytes(24));
        var backendPath = ResolveBackendPath();
        var startInfo = new ProcessStartInfo
        {
            FileName = backendPath,
            Arguments = $"--host 127.0.0.1 --port {Port} --token {Token}",
            WorkingDirectory = Path.GetDirectoryName(backendPath) ?? AppContext.BaseDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
        };
        DesktopDiagnostics.Log($"Starting bundled backend from {backendPath} on port {Port}.");
        _process = Process.Start(startInfo) ?? throw new InvalidOperationException("Failed to start backend process.");
        _process.OutputDataReceived += (_, args) => LogBackendLine("stdout", args.Data);
        _process.ErrorDataReceived += (_, args) => LogBackendLine("stderr", args.Data);
        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();
        _client = new DesktopBackendClient(new HttpClient
        {
            BaseAddress = new Uri($"http://127.0.0.1:{Port}"),
            Timeout = TimeSpan.FromSeconds(30),
        }, Token);
        await WaitForHealthyAsync(cancellationToken);
        return _client;
    }

    public async ValueTask DisposeAsync()
    {
        if (_client is not null)
        {
            try
            {
                using var shutdownClient = new HttpClient
                {
                    BaseAddress = new Uri($"http://127.0.0.1:{Port}"),
                    Timeout = TimeSpan.FromSeconds(5),
                };
                shutdownClient.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", Token);
                await shutdownClient.PostAsync("/shutdown", new StringContent(string.Empty), CancellationToken.None);
            }
            catch
            {
            }
        }

        if (_process is not null && !_process.HasExited)
        {
            _process.Kill(entireProcessTree: true);
            await _process.WaitForExitAsync();
        }
    }

    private async Task WaitForHealthyAsync(CancellationToken cancellationToken)
    {
        var deadline = DateTime.UtcNow.AddSeconds(60);
        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (_process is { HasExited: true })
            {
                DesktopDiagnostics.Log($"Bundled backend exited before health check completed with code {_process.ExitCode}.");
                throw new InvalidOperationException($"Backend exited with code {_process.ExitCode}.");
            }
            try
            {
                JsonNode? payload = await Client.GetHealthAsync(cancellationToken);
                if (payload?["status"]?.GetValue<string>() == "ok")
                {
                    return;
                }
            }
            catch
            {
            }
            await Task.Delay(250, cancellationToken);
        }
        throw new TimeoutException("Timed out waiting for desktop backend startup.");
    }

    private static int ReservePort()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }

    private static string ResolveBackendPath()
    {
        var backendExe = Path.Combine(AppContext.BaseDirectory, "backend", "DevDocsDownloader.Backend.exe");
        if (!File.Exists(backendExe))
        {
            throw new FileNotFoundException("Bundled backend executable not found.", backendExe);
        }
        return backendExe;
    }

    private static void LogBackendLine(string stream, string? line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            return;
        }
        DesktopDiagnostics.Log($"Bundled backend {stream}: {line}");
    }
}
