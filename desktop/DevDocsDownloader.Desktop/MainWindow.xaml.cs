using DevDocsDownloader.Desktop.Pages;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DevDocsDownloader.Desktop;

public sealed partial class MainWindow : Window
{
    private readonly Dictionary<string, Type> _pages = new()
    {
        ["RunPage"] = typeof(RunPage),
        ["BulkPage"] = typeof(BulkPage),
        ["LanguagesPage"] = typeof(LanguagesPage),
        ["PresetsPage"] = typeof(PresetsPage),
        ["ReportsPage"] = typeof(ReportsPage),
        ["OutputBrowserPage"] = typeof(OutputBrowserPage),
        ["CheckpointsPage"] = typeof(CheckpointsPage),
        ["CachePage"] = typeof(CachePage),
        ["SettingsPage"] = typeof(SettingsPage),
    };

    public MainWindow()
    {
        InitializeComponent();
        if (Content is FrameworkElement root)
        {
            root.DataContext = App.MainViewModel;
        }
        NavigationList.SelectedIndex = 0;
        ContentFrame.Navigate(typeof(RunPage));
    }

    private void OnSelectionChanged(object sender, SelectionChangedEventArgs args)
    {
        if ((sender as ListBox)?.SelectedItem is not ListBoxItem item || item.Tag is not string tag)
        {
            return;
        }

        if (_pages.TryGetValue(tag, out var pageType))
        {
            ContentFrame.Navigate(pageType);
        }
    }
}
