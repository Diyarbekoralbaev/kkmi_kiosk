using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Kiosk.App.Identity;
using Kiosk.App.Localization;
using Kiosk.App.Settings;

namespace Kiosk.App;

public partial class App : Application
{
    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            // Load the saved UI language BEFORE building MainWindow so every
            // {DynamicResource} in XAML resolves correctly on first render.
            LocalizationService.SetLanguage(
                LocalizationService.Parse(KioskSettings.Current.PreferredLanguage));

            // First-run enrollment vs normal kiosk launch. The store check is fast
            // (file exists?) and never triggers a DPAPI decrypt failure path here —
            // failure to decrypt later just routes back to enrollment.
            desktop.MainWindow = DeviceKeyStore.HasKey()
                ? new MainWindow()
                : new EnrollmentWindow();
        }

        base.OnFrameworkInitializationCompleted();
    }
}
