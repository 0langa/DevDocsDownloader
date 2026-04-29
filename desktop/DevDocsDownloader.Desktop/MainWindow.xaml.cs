using DevDocsDownloader.Desktop.Pages;
using System.ComponentModel;
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
        App.MainViewModel.PropertyChanged += OnMainViewModelPropertyChanged;
        StatusTextBlock.Text = App.MainViewModel.StatusText;
        ContentFrame.Navigate(typeof(RunPage));
    }

    private void OnMainViewModelPropertyChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(ViewModels.MainWindowViewModel.StatusText))
        {
            StatusTextBlock.Text = App.MainViewModel.StatusText;
        }
    }

    private void OnNavigateClick(object sender, RoutedEventArgs args)
    {
        if (sender is not Button button || button.Tag is not string tag)
        {
            return;
        }

        if (_pages.TryGetValue(tag, out var pageType))
        {
            ContentFrame.Navigate(pageType);
        }
    }
}
