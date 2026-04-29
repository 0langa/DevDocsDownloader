using DevDocsDownloader.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DevDocsDownloader.Desktop.Pages;

public sealed partial class OutputBrowserPage : Page
{
    public OutputBrowserPage()
    {
        InitializeComponent();
    }

    private async void OnListBundles(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await App.BackendHost.Client.GetOutputBundlesAsync();
            ContentBox.Text = JsonFormatter.Format(result);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }

    private async void OnLoadTree(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await App.BackendHost.Client.GetOutputTreeAsync(LanguageSlugBox.Text);
            ContentBox.Text = JsonFormatter.Format(result);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }

    private async void OnLoadFile(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await App.BackendHost.Client.GetOutputFileAsync(LanguageSlugBox.Text, RelativePathBox.Text);
            ContentBox.Text = JsonFormatter.Format(result);
        }
        catch (Exception exc)
        {
            ContentBox.Text = exc.Message;
        }
    }
}
