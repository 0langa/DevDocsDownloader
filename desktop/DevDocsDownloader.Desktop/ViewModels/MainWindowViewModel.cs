using CommunityToolkit.Mvvm.ComponentModel;

namespace DevDocsDownloader.Desktop.ViewModels;

public partial class MainWindowViewModel : ObservableObject
{
    [ObservableProperty]
    private string _statusText = "Starting backend...";

    [ObservableProperty]
    private bool _backendReady;

    public async Task InitializeAsync()
    {
        try
        {
            await App.BackendHost.StartAsync();
            StatusText = "Ready";
            BackendReady = true;
        }
        catch (Exception exc)
        {
            StatusText = $"Backend startup failed: {exc.Message}";
            BackendReady = false;
        }
    }
}
