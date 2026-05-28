using System;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.State;

namespace Kiosk.App.Controls;

/// <summary>Sticky header: clock+date on the top-left, weather (city + °C)
/// on the top-right, big gerb + 2-line title centred underneath. Mirrors
/// the 2026 mockup (`infokiosk.html`). The language toggle moved to the
/// footer; the header is purely informational.
///
/// Date format is language-specific via <see cref="LocalizationService.FormatDate"/>
/// because Windows ICU doesn't always carry Karakalpak month names.</summary>
public partial class KioskHeader : UserControl
{
    private DispatcherTimer? _clockTimer;

    public KioskHeader()
    {
        InitializeComponent();
        DataContext = SessionStore.Current;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private void OnLoaded(object? sender, RoutedEventArgs e)
    {
        UpdateClock();
        _clockTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
        _clockTimer.Tick += (_, _) => UpdateClock();
        _clockTimer.Start();

        LocalizationService.LanguageChanged += OnLanguageChanged;
    }

    private void OnUnloaded(object? sender, RoutedEventArgs e)
    {
        _clockTimer?.Stop();
        _clockTimer = null;
        LocalizationService.LanguageChanged -= OnLanguageChanged;
    }

    private void OnLanguageChanged(Language lang)
    {
        // Date format is hand-rolled per language so a Kk → Ru switch
        // needs to redraw the date line immediately rather than wait for
        // the next 1-second tick.
        Dispatcher.UIThread.Post(UpdateClock);
    }

    private void UpdateClock()
    {
        var now = DateTime.Now;
        ClockText.Text = now.ToString("HH:mm");
        DateText.Text = LocalizationService.FormatDate(now, LocalizationService.Current);
    }
}
