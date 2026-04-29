using Microsoft.UI.Xaml;
using Windows.Storage.Pickers;
using WinRT.Interop;

namespace DevDocsDownloader.Desktop.Services;

public static class FolderPickerService
{
    public static async Task<string?> PickFolderAsync(Window owner, string? initialPath = null)
    {
        _ = initialPath;
        var picker = new FolderPicker();
        picker.FileTypeFilter.Add("*");
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(owner));
        picker.SuggestedStartLocation = PickerLocationId.DocumentsLibrary;
        var selected = await picker.PickSingleFolderAsync();
        return selected?.Path;
    }
}
