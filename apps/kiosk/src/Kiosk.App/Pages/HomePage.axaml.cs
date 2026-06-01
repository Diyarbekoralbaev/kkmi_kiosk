using Avalonia.Controls;
using Avalonia.Interactivity;
using Kiosk.App.Face;
using Kiosk.App.Identity;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

public partial class HomePage : UserControl
{
    public HomePage()
    {
        InitializeComponent();
    }

    private async void OnTileAi(object? sender, RoutedEventArgs e)
    {
        // AI menen sóylesiw — opens the dedicated robot/voice page.
        //
        // Recognize the visitor HERE, on the GL-free Home page, BEFORE the robot
        // page spins up its OpenGL FBO. Running the camera concurrently with that
        // fragile Intel UHD FBO setup is what aggravates the GL crash, so we do
        // it first and stash the result for KioskRuntime to greet by name.
        // Bounded + swallowed — face recognition must never block entering AI.
        try
        {
            var creds = DeviceKeyStore.Load();
            if (creds is not null)
                FaceRecognizer.StashGreet(
                    await FaceRecognizer.RecognizeForGreetingAsync(creds.BackendUrl));
        }
        catch { /* no greeting → AI still opens normally */ }

        SessionStore.Current.Navigate(KioskPage.Ai);
    }

    private void OnTileSubmit(object? sender, RoutedEventArgs e)
    {
        // Joqarı Keńeske murajat — touch-driven appeal flow (topic + body +
        // phone, no category). The AI voice path stays on the AI tile.
        SessionStore.Current.ManualSubmitStep = ManualSubmitStep.Idle;
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
