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
        ShellNavigationView.SelectedItem = ShellNavigationView.MenuItems[0];
        ContentFrame.Navigate(typeof(RunPage));
    }

    private void OnSelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.SelectedItemContainer?.Tag is not string tag)
        {
            return;
        }

        if (_pages.TryGetValue(tag, out var pageType))
        {
            ContentFrame.Navigate(pageType);
        }
    }
}
