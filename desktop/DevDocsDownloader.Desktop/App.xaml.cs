using DevDocsDownloader.Desktop.Services;
using DevDocsDownloader.Desktop.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DevDocsDownloader.Desktop;

public partial class App : Application
{
    public static BackendProcessHost BackendHost { get; } = new();
    public static MainWindowViewModel MainViewModel { get; } = new();

    public App()
    {
        InitializeComponent();
        UnhandledException += OnUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnCurrentDomainUnhandledException;
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            MainWindow = new MainWindow();
            MainWindow.Closed += (_, _) =>
            {
                MainViewModel.Shutdown();
                BackendHost.Terminate();
            };
            MainWindow.Activate();
            await MainViewModel.InitializeAsync();
            if (!MainViewModel.BackendReady)
            {
                await ShowBackendErrorDialogAsync(MainViewModel.StatusText);
            }
        }
        catch (Exception exc)
        {
            DesktopDiagnostics.Log("Desktop shell launch failed.", exc);
            throw;
        }
    }

    private static async Task ShowBackendErrorDialogAsync(string message)
    {
        try
        {
            var dialog = new ContentDialog
            {
                Title = "Backend failed to start",
                Content = $"{message}\n\nMost features are unavailable. Check the desktop log for details.\n\n{MainViewModel.BackendLogPath}",
                CloseButtonText = "OK",
                XamlRoot = MainWindow.Content?.XamlRoot,
            };
            await dialog.ShowAsync();
        }
        catch (Exception exc)
        {
            DesktopDiagnostics.Log("Could not show backend error dialog.", exc);
        }
    }

    public static MainWindow MainWindow { get; private set; } = null!;

    private static void OnCurrentDomainUnhandledException(object sender, System.UnhandledExceptionEventArgs args)
    {
        DesktopDiagnostics.Log("Unhandled AppDomain exception.", args.ExceptionObject as Exception);
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs args)
    {
        DesktopDiagnostics.Log("Unobserved task exception.", args.Exception);
    }

    private static void OnUnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs args)
    {
        DesktopDiagnostics.Log("Unhandled WinUI exception.", args.Exception);
    }
}
