using Avalonia.Controls;
using Avalonia.Interactivity;

namespace Kiosk.App.Pages;

public enum AdminChoice
{
    None = 0,
    Exit = 1,
    Settings = 2,
}

/// <summary>Modal shown after the operator passes the PIN gate. Three buttons:
/// Exit (shutdown the app), Settings (open AdminSettingsWindow), Cancel
/// (dismiss). Caller reads <see cref="Result"/> after ShowDialog returns.</summary>
public partial class AdminChoiceDialog : Window
{
    public AdminChoice Result { get; private set; } = AdminChoice.None;

    public AdminChoiceDialog()
    {
        InitializeComponent();
    }

    private void OnExit(object? sender, RoutedEventArgs e)
    {
        Result = AdminChoice.Exit;
        Close();
    }

    private void OnSettings(object? sender, RoutedEventArgs e)
    {
        Result = AdminChoice.Settings;
        Close();
    }

    private void OnCancel(object? sender, RoutedEventArgs e)
    {
        Result = AdminChoice.None;
        Close();
    }
}
