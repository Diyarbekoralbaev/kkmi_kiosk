using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;

namespace Kiosk.App.Pages;

/// <summary>
/// Makes a modal dialog survivable on a kiosk, where nobody can move a window,
/// alt-tab to it, or drag its edge.
///
/// Two things go wrong without this, and both look identical from the corridor
/// — the screen stops responding to touch and nothing new appears:
///
///   * The dialog opens BEHIND the main window. MainWindow runs fullscreen and
///     Topmost in release builds, and an owned window does not reliably win
///     against that. The dialog is modal either way, so every touch on the page
///     underneath is swallowed by a dialog the visitor cannot see.
///
///   * The dialog is taller than the screen. AdminPinDialog is a fixed 820 px
///     because it carries a numeric keypad; on a 768-tall panel the keypad and
///     both buttons sit below the bottom edge. It is modal and CanResize=False,
///     so there is no way to finish it and no way to cancel it.
///
/// Neither is recoverable without a keyboard, and these machines have none.
/// </summary>
internal static class KioskDialog
{
    /// <summary>Breathing room left around a clamped dialog so it reads as a
    /// dialog rather than as a second full screen.</summary>
    private const double ScreenMargin = 48;

    /// <summary>Call before ShowDialog. Raises the dialog above the topmost
    /// main window and, once it knows which screen it is on, shrinks it to fit
    /// and makes its content scroll if the shrink cost anything.</summary>
    public static void Prepare(Window dialog)
    {
        dialog.Topmost = true;
        dialog.Opened += (_, _) => FitToScreen(dialog);
    }

    private static void FitToScreen(Window dialog)
    {
        // ScreenFromWindow needs a placed window, which is why this runs from
        // Opened rather than from the constructor.
        var screen = dialog.Screens?.ScreenFromWindow(dialog) ?? dialog.Screens?.Primary;
        if (screen is null) return;

        var scaling = screen.Scaling > 0 ? screen.Scaling : 1.0;
        var maxHeight = screen.WorkingArea.Height / scaling - ScreenMargin;
        var maxWidth = screen.WorkingArea.Width / scaling - ScreenMargin;
        if (maxHeight <= 0 || maxWidth <= 0) return;

        var clamped = false;
        if (dialog.Height > maxHeight)
        {
            dialog.Height = maxHeight;
            clamped = true;
        }
        if (dialog.Width > maxWidth)
        {
            dialog.Width = maxWidth;
            clamped = true;
        }
        if (!clamped) return;

        // Shrinking alone would just crop the keypad. Reparent whatever the
        // dialog already holds into a scroller so the parts that no longer fit
        // stay reachable — the named controls keep working, since the fields
        // InitializeComponent set point at the same objects.
        if (dialog.Content is Control content and not ScrollViewer)
        {
            dialog.Content = new ScrollViewer
            {
                Content = content,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                VerticalAlignment = VerticalAlignment.Stretch,
            };
        }

        // Re-centre: the window was placed for the size it no longer has.
        dialog.Position = new PixelPoint(
            screen.WorkingArea.X + (int)((screen.WorkingArea.Width - dialog.Width * scaling) / 2),
            screen.WorkingArea.Y + (int)((screen.WorkingArea.Height - dialog.Height * scaling) / 2));
    }
}
