using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class CheckpointsPage : Page
{
    public CheckpointsPage()
    {
        InitializeComponent();
    }

    private async void OnList(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await App.BackendHost.Client.GetCheckpointsAsync();
            ContentBox.Text = JsonFormatter.Format(result);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }

    private async void OnLoad(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await App.BackendHost.Client.GetCheckpointAsync(SlugBox.Text);
            ContentBox.Text = JsonFormatter.Format(result);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }

    private async void OnDelete(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await App.BackendHost.Client.DeleteCheckpointAsync(SlugBox.Text);
            ContentBox.Text = JsonFormatter.Format(result);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }
}
