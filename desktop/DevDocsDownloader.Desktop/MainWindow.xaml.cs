using DevDocsDownloader.Desktop.Pages;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI;
using Windows.Graphics;
using CommunityToolkit.Mvvm.ComponentModel;
using WinRT.Interop;

namespace DevDocsDownloader.Desktop;

public sealed partial class MainWindow : Window
{
    private const int MinimumWindowWidth = 1280;
    private const int MinimumWindowHeight = 860;
    private const uint WmGetMinMaxInfo = 0x0024;
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
    private readonly Dictionary<string, Page> _pageCache = [];
    private readonly Dictionary<string, Button> _navButtons = [];
    private readonly TextBlock _statusTextBlock;
    private readonly TextBlock _outputRootTextBlock;
    private readonly TextBlock _jobLabelTextBlock;
    private readonly TextBlock _activityTextBlock;
    private readonly TextBlock _warningTextBlock;
    private readonly Border _errorHintBorder;
    private readonly TextBlock _errorHintTextBlock;
    private readonly ProgressBar _progressBar;
    private readonly TextBlock _sourceHealthTextBlock;
    private readonly Button _cancelJobButton;
    private readonly Frame _contentFrame;
    private readonly nint _windowHandle;
    private readonly SubclassProc _subclassProc;
    private string _activePageKey = "RunPage";

    public MainWindow()
    {
        InitializeComponent();
        Title = "DevDocsDownloader";
        var root = new Grid();
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(260) });
        root.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        var sidebarBorder = new Border
        {
            Padding = new Thickness(16, 20, 16, 20),
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 24, 28, 36)),
        };
        Grid.SetColumn(sidebarBorder, 0);
        Grid.SetRowSpan(sidebarBorder, 2);

        var sidebar = new StackPanel { Spacing = 8 };
        sidebarBorder.Child = sidebar;
        sidebar.Children.Add(new TextBlock
        {
            Text = "DevDocsDownloader",
            FontSize = 28,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
            Foreground = new SolidColorBrush(Colors.White),
            Margin = new Thickness(0, 0, 0, 4),
        });
        _statusTextBlock = new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            Opacity = 0.85,
            Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 214, 220, 232)),
            Margin = new Thickness(0, 0, 0, 4),
        };
        sidebar.Children.Add(_statusTextBlock);
        _outputRootTextBlock = new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            Opacity = 0.75,
            FontSize = 12,
            Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 180, 188, 204)),
            Margin = new Thickness(0, 0, 0, 12),
        };
        sidebar.Children.Add(_outputRootTextBlock);
        _sourceHealthTextBlock = new TextBlock
        {
            Opacity = 0.85,
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 180, 188, 204)),
            Margin = new Thickness(0, 0, 0, 10),
        };
        sidebar.Children.Add(_sourceHealthTextBlock);

        sidebar.Children.Add(new Border
        {
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 37, 44, 56)),
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(12),
            Margin = new Thickness(0, 0, 0, 12),
            Child = new StackPanel
            {
                Spacing = 8,
                Children =
                {
                    new TextBlock
                    {
                        Text = "Active Job",
                        FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                        Foreground = new SolidColorBrush(Colors.White),
                    },
                    (_jobLabelTextBlock = new TextBlock
                    {
                        Text = "No active job.",
                        TextWrapping = TextWrapping.Wrap,
                        Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 214, 220, 232)),
                    }),
                    (_progressBar = new ProgressBar
                    {
                        Minimum = 0,
                        Maximum = 100,
                        Visibility = Visibility.Collapsed,
                    }),
                    (_activityTextBlock = new TextBlock
                    {
                        TextWrapping = TextWrapping.Wrap,
                        FontSize = 12,
                        Opacity = 0.8,
                        Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 180, 188, 204)),
                    }),
                    (_warningTextBlock = new TextBlock
                    {
                        TextWrapping = TextWrapping.Wrap,
                        FontSize = 12,
                        Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 255, 206, 120)),
                    }),
                    (_errorHintBorder = new Border
                    {
                        Padding = new Thickness(8),
                        Background = new SolidColorBrush(ColorHelper.FromArgb(255, 74, 52, 18)),
                        Visibility = Visibility.Collapsed,
                        Child = (_errorHintTextBlock = new TextBlock
                        {
                            TextWrapping = TextWrapping.Wrap,
                            FontSize = 12,
                            Foreground = new SolidColorBrush(ColorHelper.FromArgb(255, 255, 220, 160)),
                        }),
                    }),
                    (_cancelJobButton = new Button
                    {
                        Content = "Cancel active job",
                        HorizontalAlignment = HorizontalAlignment.Stretch,
                        Visibility = Visibility.Collapsed,
                    }),
                },
            },
        });
        _cancelJobButton.Click += OnCancelJobClick;
        _windowHandle = WindowNative.GetWindowHandle(this);
        _subclassProc = WindowSubclassProc;

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
                HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Left,
                Padding = new Thickness(14, 10, 14, 10),
                CornerRadius = new CornerRadius(8),
            };
            button.Click += OnNavigateClick;
            _navButtons[entry.Item2] = button;
            sidebar.Children.Add(button);
        }

        var headerBorder = new Border
        {
            Background = new SolidColorBrush(ColorHelper.FromArgb(255, 17, 24, 39)),
            Padding = new Thickness(20, 16, 20, 16),
            Child = new StackPanel
            {
                Spacing = 4,
                Children =
                {
                    new TextBlock
                    {
                        Text = "Operator Dashboard",
                        FontSize = 24,
                        FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
                    },
                    new TextBlock
                    {
                        Text = "Runs, catalogs, output, reports, checkpoints, and cache all stay live while you move around the shell.",
                        Opacity = 0.75,
                        TextWrapping = TextWrapping.Wrap,
                    },
                },
            },
        };
        Grid.SetColumn(headerBorder, 1);
        Grid.SetRow(headerBorder, 0);

        _contentFrame = new Frame
        {
            Margin = new Thickness(20),
            IsTabStop = false,
        };
        Grid.SetColumn(_contentFrame, 1);
        Grid.SetRow(_contentFrame, 1);

        root.Children.Add(sidebarBorder);
        root.Children.Add(headerBorder);
        root.Children.Add(_contentFrame);
        Content = root;
        var iconCandidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "DevDocsDownloader.ico"),
            Path.Combine(AppContext.BaseDirectory, "Assets", "DevDocsDownloader.ico"),
        };
        var iconPath = iconCandidates.FirstOrDefault(File.Exists);
        if (!string.IsNullOrWhiteSpace(iconPath))
        {
            AppWindow.SetIcon(iconPath);
        }
        SetWindowSubclass(_windowHandle, _subclassProc, 1, 0);
        AppWindow.Resize(new SizeInt32(MinimumWindowWidth, MinimumWindowHeight));
        Closed += OnClosed;
        App.MainViewModel.PropertyChanged += OnMainViewModelPropertyChanged;
        ApplyShellState();
        NavigateTo("RunPage");
    }

    private void OnClosed(object sender, WindowEventArgs args)
    {
        RemoveWindowSubclass(_windowHandle, _subclassProc, 1);
    }

    private void OnMainViewModelPropertyChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName is nameof(ViewModels.MainWindowViewModel.StatusText)
            or nameof(ViewModels.MainWindowViewModel.CurrentOutputRoot)
            or nameof(ViewModels.MainWindowViewModel.ActiveJobId)
            or nameof(ViewModels.MainWindowViewModel.ActiveJobLabel)
            or nameof(ViewModels.MainWindowViewModel.LatestActivity)
            or nameof(ViewModels.MainWindowViewModel.WarningCount)
            or nameof(ViewModels.MainWindowViewModel.FailureCount)
            or nameof(ViewModels.MainWindowViewModel.LastErrorHint)
            or nameof(ViewModels.MainWindowViewModel.ProgressVisible)
            or nameof(ViewModels.MainWindowViewModel.ProgressIndeterminate)
            or nameof(ViewModels.MainWindowViewModel.ProgressValue)
            or nameof(ViewModels.MainWindowViewModel.BackendReady)
            or nameof(ViewModels.MainWindowViewModel.SourceHealth))
        {
            ApplyShellState();
        }
    }

    private void OnNavigateClick(object sender, RoutedEventArgs args)
    {
        if (sender is not Button button || button.Tag is not string tag)
        {
            return;
        }

        NavigateTo(tag);
    }

    public void NavigateTo(string tag)
    {
        if (!_pages.TryGetValue(tag, out _))
        {
            return;
        }
        _activePageKey = tag;
        _contentFrame.Content = GetOrCreatePage(tag);
        UpdateNavState();
    }

    public T? GetCachedPage<T>() where T : Page
    {
        return _pageCache.Values.OfType<T>().FirstOrDefault();
    }

    private Page GetOrCreatePage(string tag)
    {
        if (_pageCache.TryGetValue(tag, out var existing))
        {
            return existing;
        }
        var pageType = _pages[tag];
        var page = (Page)Activator.CreateInstance(pageType)!;
        _pageCache[tag] = page;
        return page;
    }

    private async void OnCancelJobClick(object sender, RoutedEventArgs e)
    {
        await App.MainViewModel.CancelActiveJobAsync();
    }

    private void ApplyShellState()
    {
        _statusTextBlock.Text = App.MainViewModel.StatusText;
        _outputRootTextBlock.Text = string.IsNullOrWhiteSpace(App.MainViewModel.CurrentOutputRoot)
            ? "Output root loading..."
            : $"Output root\n{App.MainViewModel.CurrentOutputRoot}";
        _sourceHealthTextBlock.Text = BuildSourceHealthText(App.MainViewModel.SourceHealth);
        _jobLabelTextBlock.Text = string.IsNullOrWhiteSpace(App.MainViewModel.ActiveJobLabel)
            ? "No active job."
            : App.MainViewModel.ActiveJobLabel;
        _activityTextBlock.Text = App.MainViewModel.LatestActivity;
        _warningTextBlock.Text = App.MainViewModel.WarningCount > 0 || App.MainViewModel.FailureCount > 0
            ? $"Warnings: {App.MainViewModel.WarningCount}   Failures: {App.MainViewModel.FailureCount}"
            : "";
        _errorHintTextBlock.Text = App.MainViewModel.LastErrorHint;
        _errorHintBorder.Visibility = string.IsNullOrWhiteSpace(App.MainViewModel.LastErrorHint)
            ? Visibility.Collapsed
            : Visibility.Visible;
        _progressBar.Visibility = App.MainViewModel.ProgressVisible ? Visibility.Visible : Visibility.Collapsed;
        _progressBar.IsIndeterminate = App.MainViewModel.ProgressIndeterminate;
        _progressBar.Value = App.MainViewModel.ProgressValue;
        _cancelJobButton.Visibility = !string.IsNullOrWhiteSpace(App.MainViewModel.ActiveJobId) && App.MainViewModel.BackendReady
            ? Visibility.Visible
            : Visibility.Collapsed;
    }

    private static string BuildSourceHealthText(JsonObject payload)
    {
        if (payload.Count == 0)
        {
            return "Sources: unknown";
        }
        var dots = new List<string>();
        foreach (var source in new[] { "devdocs", "mdn", "dash", "web_page" })
        {
            var node = payload[source] as JsonObject;
            var status = node?["status"]?.GetValue<string>() ?? "unknown";
            var icon = status switch
            {
                "ok" => "●",
                "degraded" => "◐",
                _ => "○",
            };
            dots.Add($"{source}:{icon}");
        }
        return $"Sources {string.Join(" ", dots)}";
    }

    private void UpdateNavState()
    {
        foreach (var (key, button) in _navButtons)
        {
            var selected = key == _activePageKey;
            button.Background = new SolidColorBrush(
                selected ? ColorHelper.FromArgb(255, 29, 78, 216) : ColorHelper.FromArgb(255, 37, 44, 56));
            button.Foreground = new SolidColorBrush(Colors.White);
            button.BorderBrush = new SolidColorBrush(
                selected ? ColorHelper.FromArgb(255, 96, 165, 250) : ColorHelper.FromArgb(255, 55, 65, 81));
        }
    }

    private nint WindowSubclassProc(nint hWnd, uint msg, nuint wParam, nint lParam, nuint uIdSubclass, nuint dwRefData)
    {
        if (msg == WmGetMinMaxInfo)
        {
            var info = Marshal.PtrToStructure<MinMaxInfo>(lParam);
            info.ptMinTrackSize = new NativePoint(MinimumWindowWidth, MinimumWindowHeight);
            Marshal.StructureToPtr(info, lParam, false);
        }

        return DefSubclassProc(hWnd, msg, wParam, lParam);
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct NativePoint
    {
        public int X;
        public int Y;

        public NativePoint(int x, int y)
        {
            X = x;
            Y = y;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MinMaxInfo
    {
        public NativePoint ptReserved;
        public NativePoint ptMaxSize;
        public NativePoint ptMaxPosition;
        public NativePoint ptMinTrackSize;
        public NativePoint ptMaxTrackSize;
    }

    private delegate nint SubclassProc(nint hWnd, uint msg, nuint wParam, nint lParam, nuint uIdSubclass, nuint dwRefData);

    [DllImport("comctl32.dll", SetLastError = true)]
    private static extern bool SetWindowSubclass(nint hWnd, SubclassProc pfnSubclass, nuint uIdSubclass, nuint dwRefData);

    [DllImport("comctl32.dll", SetLastError = true)]
    private static extern bool RemoveWindowSubclass(nint hWnd, SubclassProc pfnSubclass, nuint uIdSubclass);

    [DllImport("comctl32.dll", SetLastError = true)]
    private static extern nint DefSubclassProc(nint hWnd, uint msg, nuint wParam, nint lParam);
}
