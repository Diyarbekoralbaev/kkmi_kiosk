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

    private void OnTileQabul(object? sender, RoutedEventArgs e)
    {
        // Jeke qabılǵa jazılıw — reception registration. No official, no
        // date; the citizen leaves a phone and the Council calls back. Reset
        // the step to Idle so QabulPage treats this as a fresh touch entry —
        // not a leftover voice-preview state from an abandoned AI session.
        SessionStore.Current.AppointmentStep = AppointmentStep.Idle;
        SessionStore.Current.Navigate(KioskPage.Qabul);
    }

    private void OnTileFeedback(object? sender, RoutedEventArgs e)
    {
        // Shaǵım / usınıs / minnetdarshılıq — feedback flow. Reset the step so
        // a stale voice preview can't leak into the touch entry.
        SessionStore.Current.ManualFeedbackStep = ManualFeedbackStep.Idle;
        SessionStore.Current.Navigate(KioskPage.Feedback);
    }
}
