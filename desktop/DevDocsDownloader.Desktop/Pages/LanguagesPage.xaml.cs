using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class LanguagesPage : Page
{
    public LanguagesPage()
    {
        InitializeComponent();
    }

    private async void OnRefresh(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await App.BackendHost.Client.GetLanguagesAsync();
            ContentBox.Text = JsonFormatter.Format(result);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }
}
