using System.Text.Json.Nodes;
using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class PresetsPage : Page
{
    public PresetsPage()
    {
        InitializeComponent();
    }

    private async void OnLoadPresets(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await App.BackendHost.Client.GetPresetsAsync();
            ContentBox.Text = JsonFormatter.Format(result);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }

    private async void OnAuditPresets(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await App.BackendHost.Client.AuditPresetsAsync(new JsonObject());
            ContentBox.Text = JsonFormatter.Format(result);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }
}
