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
        // AI menen sóylesiw — opens the dedicated robot/voice page.
        SessionStore.Current.Navigate(KioskPage.Ai);
    }

    private void OnTileSubmit(object? sender, RoutedEventArgs e)
    {
        // Joqarı Keńeske murajat — touch-driven appeal flow (topic + body +
        // phone, no category). The AI voice path stays on the AI tile.
        SessionStore.Current.Navigate(KioskPage.ManualSubmit);
    }

    private void OnTileQabul(object? sender, RoutedEventArgs e)
    {
        // Jeke qabılǵa jazılıw — reception registration. No official, no
        // date; the citizen leaves a phone and the Council calls back.
        SessionStore.Current.Navigate(KioskPage.Qabul);
    }

    private void OnTileFeedback(object? sender, RoutedEventArgs e)
    {
        // Shaǵım / usınıs / minnetdarshılıq — feedback flow.
        SessionStore.Current.Navigate(KioskPage.Feedback);
    }
}
