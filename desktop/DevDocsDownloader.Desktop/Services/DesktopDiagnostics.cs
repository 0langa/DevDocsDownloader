using System.Text;

namespace DevDocsDownloader.Desktop.Services;

public static class DesktopDiagnostics
{
    public static string LogPath =>
        Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "DevDocsDownloader",
            "logs",
            "desktop-shell.log"
        );

    public static void Log(string message, Exception? exception = null)
    {
        try
        {
            var path = LogPath;
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var builder = new StringBuilder();
            builder.Append('[').Append(DateTimeOffset.Now.ToString("O")).Append("] ").AppendLine(message);
            if (exception is not null)
            {
                builder.AppendLine(exception.ToString());
            }
            File.AppendAllText(path, builder.ToString(), Encoding.UTF8);
        }
        catch
        {
        }
    }
}
