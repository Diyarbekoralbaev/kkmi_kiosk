using Avalonia.Controls;
using Avalonia.Threading;
using Kiosk.App.Localization;

namespace Kiosk.App.Pages;

/// <summary>
/// Full-screen "system updating" overlay. Driven imperatively by MainWindow's
/// startup flow; not bound to SessionStore to keep the update path independent
/// of the rest of the app state (the runtime isn't even started yet).
/// </summary>
public partial class UpdatingPage : UserControl
{
    public UpdatingPage()
    {
        InitializeComponent();
    }

    public void SetVersion(string version)
    {
        Dispatcher.UIThread.Post(() =>
            VersionLine.Text = LocalizationService.Get("UpdatingVersionLabel") + version);
    }

    public void SetStatus(string status)
    {
        Dispatcher.UIThread.Post(() => StatusLine.Text = status);
    }

    public void SetProgress(double fraction)
    {
        // 520 is the bar's outer width; subtract the 4 px inner padding so
        // the fill clears the rounded corner.
        var px = System.Math.Max(0, System.Math.Min(516, fraction * 516));
        Dispatcher.UIThread.Post(() =>
        {
            ProgressFill.Width = px;
            StatusLine.Text = $"{LocalizationService.Get("UpdatingDownloadingLabel")} {(int)(fraction * 100)}%";
        });
    }
}
