using DevDocsDownloader.Desktop.Services;
using DevDocsDownloader.Desktop.ViewModels;
using Microsoft.UI.Xaml;

namespace DevDocsDownloader.Desktop;

public partial class App : Application
{
    public static BackendProcessHost BackendHost { get; } = new();
    public static MainWindowViewModel MainViewModel { get; } = new();

    public App()
    {
        InitializeComponent();
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        MainWindow = new MainWindow();
        MainWindow.Activate();
        await MainViewModel.InitializeAsync();
    }

    public static MainWindow MainWindow { get; private set; } = null!;
}
