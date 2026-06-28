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
        // Joqarı Keńeske murajat — touch-driven appeal flow (phone → lookup →
        // confirm/full-form → text → preview). Reset the step to Idle so the
        // page starts fresh — not a leftover voice-preview state from an
        // abandoned AI session.
        SessionStore.Current.SubmitStep = SubmitStep.Idle;
        SessionStore.Current.Navigate(KioskPage.ManualSubmit);
    }
}
