using Avalonia;
using Avalonia.Media;

namespace Kiosk.App;

/// <summary>
/// Resolves the palette tokens declared in <c>App.axaml</c> from code-behind.
///
/// Why this exists: App.axaml calls itself the "single-file palette swap
/// point", but that was only true for XAML. Code-behind paths (MicOrb state
/// colours, AdminSettings status text) carried their own hex literals, so the
/// pre-KKMI re-theme would have silently missed them — 55 stale literals had
/// accumulated across 18 files. Going through here keeps App.axaml the single
/// source for every path.
///
/// Unknown token = a typo in a compile-time-constant string, so it surfaces on
/// first render rather than shipping: we fall back to magenta, which is
/// impossible to mistake for a designed colour.
///
/// Named Palette, not Theme: every Control inherits an Avalonia
/// <c>Theme</c> property of type ControlTheme, and C# member lookup beats
/// namespace-level type lookup — a class called Theme is unreachable from
/// any code-behind.
/// </summary>
public static class Palette
{
    private static readonly IBrush Fallback = new SolidColorBrush(Colors.Magenta);

    public static IBrush Brush(string token)
    {
        if (Application.Current?.Resources.TryGetResource(token, null, out var v) == true
            && v is IBrush b)
        {
            return b;
        }
        return Fallback;
    }
}
