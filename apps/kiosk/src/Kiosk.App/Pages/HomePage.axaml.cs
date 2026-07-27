using Avalonia.Controls;
using Avalonia.Interactivity;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>Home menu. Each tile resets any half-finished flow before
/// navigating: a visitor who walked away mid-appeal leaves the step machine
/// dirty, and the next person must not land in someone else's form.</summary>
public partial class HomePage : UserControl
{
    public HomePage()
    {
        InitializeComponent();
    }

    private static void Go(KioskPage page)
    {
        var s = SessionStore.Current;
        s.SubmitStep = SubmitStep.Idle;
        s.Navigate(page);
    }

    private void OnTileAi(object? sender, RoutedEventArgs e) => Go(KioskPage.Ai);
    private void OnTileLibrary(object? sender, RoutedEventArgs e) => Go(KioskPage.Library);
    private void OnTileAbituriyent(object? sender, RoutedEventArgs e) => Go(KioskPage.Abituriyent);
    private void OnTileMurojat(object? sender, RoutedEventArgs e) => Go(KioskPage.Murojat);
    private void OnTileSchedule(object? sender, RoutedEventArgs e) => Go(KioskPage.Jadval);
    private void OnTileReception(object? sender, RoutedEventArgs e) => Go(KioskPage.Qabul);
}
