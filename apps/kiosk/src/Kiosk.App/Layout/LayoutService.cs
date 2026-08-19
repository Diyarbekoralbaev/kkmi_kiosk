using System;
using System.Linq;
using Avalonia;
using Avalonia.Controls;

namespace Kiosk.App.Layout;

/// <summary>Which way round the panel this kiosk is bolted to.</summary>
public enum ScreenShape
{
    /// <summary>1080×1572 lobby panel — what the UI was designed against.</summary>
    Portrait,
    /// <summary>1920×1080 on a floor stand.</summary>
    Landscape,
}

/// <summary>
/// Promotes the metrics dictionary matching the screen the kiosk is actually
/// running on. Deliberately the same mechanism <see cref="Localization.LocalizationService"/>
/// uses for languages, for the same reason: both dictionaries must be declared
/// in App.axaml so the Avalonia XAML compiler resolves them at build time.
/// A ResourceInclude built at runtime is stripped by the Native AOT trimmer and
/// dies with "No precompiled XAML found for avares://…", which is exactly the
/// bug the locale code carries a comment about.
///
/// Portrait is declared last in App.axaml and therefore wins by default:
/// Avalonia walks MergedDictionaries in reverse, so a kiosk that never calls
/// <see cref="Apply"/> — or one whose screen query fails — renders precisely
/// the layout that is already in service in the lobby.
///
/// Consumers must read metrics through <c>{DynamicResource}</c>. The shape is
/// resolved once the main window knows its screen, which is after the page
/// XAML has loaded; StaticResource would have latched the portrait value.
/// </summary>
public static class LayoutService
{
    public static ScreenShape Current { get; private set; } = ScreenShape.Portrait;

    /// <summary>Fired after the new dictionary is in force. For layout that
    /// cannot be expressed as a resource value — the home grid's column count
    /// is the only one today — code-behind rebuilds itself here.</summary>
    public static event Action<ScreenShape>? ShapeChanged;

    /// <summary>Six services, two rows deep either way round: 2×3 standing up,
    /// 3×2 lying down. Not a resource because Grid's row and column
    /// definitions are a collection, not a value.</summary>
    public static int HomeTileColumns => Current == ScreenShape.Landscape ? 3 : 2;

    public static ScreenShape ShapeFor(double width, double height) =>
        width > height ? ScreenShape.Landscape : ScreenShape.Portrait;

    /// <summary>Work out which shape this window is living on.
    ///
    /// A fullscreen kiosk asks the screen, not itself: the window's own bounds
    /// are not necessarily final at the moment the window opens, because the
    /// compositor applies fullscreen asynchronously, and a half-applied size
    /// would pick the wrong dictionary. A windowed build asks itself, so a
    /// developer can drag the window to 1080×1572 and see the portrait layout
    /// on a landscape desktop.
    ///
    /// Falls back to portrait when neither reports a usable size — headless
    /// runs, and X11 before the WM has placed the window.</summary>
    public static ScreenShape DetectFor(Window window)
    {
        var fullscreen = window.WindowState == WindowState.FullScreen;

        if (!fullscreen)
        {
            var size = window.Bounds.Size;
            if (size.Width > 0 && size.Height > 0)
                return ShapeFor(size.Width, size.Height);
        }

        if (window.Screens?.Primary?.Bounds is { Width: > 0, Height: > 0 } b)
            return ShapeFor(b.Width, b.Height);

        var fallback = window.Bounds.Size;
        if (fallback.Width > 0 && fallback.Height > 0)
            return ShapeFor(fallback.Width, fallback.Height);

        return ScreenShape.Portrait;
    }

    /// <summary>Idempotent — re-applying the shape already in force does
    /// nothing, so it is safe to call from a SizeChanged handler that fires on
    /// every frame of a window drag.</summary>
    public static void Apply(ScreenShape shape)
    {
        var app = Application.Current;
        if (app is null) return;
        if (shape == Current && _applied) return;

        var sentinel = shape == ScreenShape.Landscape
            ? "_Layout_landscape"
            : "_Layout_portrait";

        var dicts = app.Resources.MergedDictionaries;
        // Identify by sentinel key rather than by Source: the compiler resolves
        // ResourceInclude at build time and the runtime objects expose no
        // stable Source to match on. Same reasoning as SetLanguage.
        IResourceProvider? target = null;
        foreach (var d in dicts.ToList())
        {
            if (d.TryGetResource(sentinel, null, out _))
            {
                target = d;
                break;
            }
        }
        if (target is null)
        {
            // App.axaml edited inconsistently. Leave whatever order was
            // declared — that is portrait, which is the safe one to be wrong on.
            Console.Error.WriteLine($"[layout] no dictionary owns {sentinel}; staying on the declared order");
            return;
        }

        // Last entry wins on lookup.
        dicts.Remove(target);
        dicts.Add(target);

        Current = shape;
        _applied = true;
        ShapeChanged?.Invoke(shape);
    }

    private static bool _applied;
}
