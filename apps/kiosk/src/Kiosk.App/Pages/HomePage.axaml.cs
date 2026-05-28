using Avalonia.Controls;
using Avalonia.Interactivity;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

public partial class HomePage : UserControl
{
    public HomePage()
    {
        InitializeComponent();
    }

    private void OnTileAi(object? sender, RoutedEventArgs e)
    {
        // AI assistant — opens the dedicated robot page. Clear any leftover
        // qabul role filter from a prior session.
        SessionStore.Current.QabulRoleFilter = "";
        SessionStore.Current.Navigate(KioskPage.Ai);
    }

    private void OnTileSubmit(object? sender, RoutedEventArgs e)
    {
        // Manual murajaat flow — touch-driven, on-screen keyboard. The
        // AI voice path stays accessible via the AI Yordamchi tile.
        SessionStore.Current.QabulRoleFilter = "";
        SessionStore.Current.Navigate(KioskPage.ManualSubmit);
    }

    private void OnTileDeputy(object? sender, RoutedEventArgs e)
    {
        // "Hokim orinbosari qabili" — QabulPage will show only role=deputy.
        SessionStore.Current.QabulRoleFilter = "deputy";
        SessionStore.Current.Navigate(KioskPage.Qabul);
    }

    private void OnTileMayor(object? sender, RoutedEventArgs e)
    {
        // "Hokim jeke qabili" — QabulPage will show only role=chief
        // (single official in the default seed).
        SessionStore.Current.QabulRoleFilter = "chief";
        SessionStore.Current.Navigate(KioskPage.Qabul);
    }
}
