using DevDocsDownloader.Desktop.Pages;
using System.ComponentModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI;

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
    private readonly TextBlock _statusTextBlock;
    private readonly Frame _contentFrame;

    public MainWindow()
    {
        Title = "DevDocsDownloader";
        var root = new Grid();
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(260) });
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        var sidebarBorder = new Border
        {
            Padding = new Thickness(16),
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 243, 244, 246)),
        };
        Grid.SetColumn(sidebarBorder, 0);

        var sidebar = new StackPanel();
        sidebarBorder.Child = sidebar;
        sidebar.Children.Add(new TextBlock
        {
            Text = "DevDocsDownloader",
            FontSize = 20,
            Margin = new Thickness(0, 0, 0, 8),
        });
        _statusTextBlock = new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            Opacity = 0.7,
            Margin = new Thickness(0, 0, 0, 16),
        };
        sidebar.Children.Add(_statusTextBlock);

        foreach (var entry in new[]
        {
            ("Dashboard / Run", "RunPage"),
            ("Bulk", "BulkPage"),
            ("Languages", "LanguagesPage"),
            ("Presets / Audit", "PresetsPage"),
            ("Reports", "ReportsPage"),
            ("Output Browser", "OutputBrowserPage"),
            ("Checkpoints", "CheckpointsPage"),
            ("Cache", "CachePage"),
            ("Settings / Help", "SettingsPage"),
        })
        {
            var button = new Button
            {
                Content = entry.Item1,
                Tag = entry.Item2,
                Margin = new Thickness(0, 0, 0, 8),
            };
            button.Click += OnNavigateClick;
            sidebar.Children.Add(button);
        }

        _contentFrame = new Frame
        {
            Margin = new Thickness(16),
        };
        Grid.SetColumn(_contentFrame, 1);

        root.Children.Add(sidebarBorder);
        root.Children.Add(_contentFrame);
        Content = root;
        App.MainViewModel.PropertyChanged += OnMainViewModelPropertyChanged;
        _statusTextBlock.Text = App.MainViewModel.StatusText;
        _contentFrame.Navigate(typeof(RunPage));
    }

    private void OnMainViewModelPropertyChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(ViewModels.MainWindowViewModel.StatusText))
        {
            _statusTextBlock.Text = App.MainViewModel.StatusText;
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
            _contentFrame.Navigate(pageType);
        }
    }
}
