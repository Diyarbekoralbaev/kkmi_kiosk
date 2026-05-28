using System;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Kiosk.App.Identity;
using Kiosk.App.Net;

namespace Kiosk.App.Controls;

/// <summary>Circular face avatar for an Official.
///
/// Renders one of two states:
///   • Photo — when Official.HasPhoto is true and the public photo
///     endpoint returned bytes successfully. The image is fetched once
///     per attach; concurrent fetches for the same id are de-duped via
///     a static in-memory cache so a picker showing 6 officials only
///     pays the HTTP cost on first display, not every re-render.
///   • Initials — when HasPhoto is false OR the fetch failed. Two
///     letters from the first two name tokens, white on a coloured
///     disc (amber for chiefs, deep blue for deputies).
///
/// Diameter is controlled by the Diameter styled property (default
/// 140). The control sizes itself to that and scales font / text /
/// borders to match.
/// </summary>
public partial class OfficialAvatar : UserControl
{
    public static readonly StyledProperty<Official?> OfficialProperty =
        AvaloniaProperty.Register<OfficialAvatar, Official?>(nameof(Official));

    public static readonly StyledProperty<double> DiameterProperty =
        AvaloniaProperty.Register<OfficialAvatar, double>(nameof(Diameter), 140);

    public Official? Official
    {
        get => GetValue(OfficialProperty);
        set => SetValue(OfficialProperty, value);
    }

    public double Diameter
    {
        get => GetValue(DiameterProperty);
        set => SetValue(DiameterProperty, value);
    }

    // Shared HttpClient so we don't churn sockets on every avatar
    // render. Avalonia 12 supports SocketsHttpHandler under AOT.
    private static readonly HttpClient _http = new()
    {
        Timeout = TimeSpan.FromSeconds(8),
    };

    // Static byte cache keyed by official id. Photos are <2 MB each; a
    // typical org has <10 officials → at most ~20 MB resident, which
    // is fine for a long-lived kiosk session. Cleared on app restart.
    private static readonly System.Collections.Concurrent.ConcurrentDictionary<string, byte[]> _photoCache = new();

    private CancellationTokenSource? _loadCts;

    public OfficialAvatar()
    {
        InitializeComponent();
        // Recompute on attach + on Official change. Diameter changes
        // also reflow the visuals so larger callers (the chief hero
        // card uses 220, deputies use 140) get scaled correctly.
        AttachedToVisualTree += (_, _) => Refresh();
        PropertyChanged += (_, e) =>
        {
            if (e.Property == OfficialProperty || e.Property == DiameterProperty)
                Refresh();
        };
    }

    private void Refresh()
    {
        var d = Diameter;
        Root.Width = d;
        Root.Height = d;
        Initials.FontSize = d * 0.34;

        // Cancel any in-flight load from a previous binding.
        _loadCts?.Cancel();
        _loadCts = null;

        var o = Official;
        if (o is null)
        {
            ShowInitials("?", isChief: false);
            return;
        }

        // Default: show initials immediately. If photo loads, swap.
        ShowInitials(InitialsFor(o.Name), isChief: o.Role == "chief");

        if (!o.HasPhoto) return;

        // Cached? Render synchronously.
        if (_photoCache.TryGetValue(o.Id, out var cached))
        {
            try
            {
                using var ms = new MemoryStream(cached);
                PhotoImage.Source = new Bitmap(ms);
                PhotoFrame.IsVisible = true;
                FallbackCircle.IsVisible = false;
                return;
            }
            catch { /* fall through to re-fetch */ }
        }

        // Fetch in background. UI stays on the initials fallback until
        // the bytes arrive — no blocking, no flicker on first render.
        _loadCts = new CancellationTokenSource();
        _ = LoadPhotoAsync(o.Id, _loadCts.Token);
    }

    private async Task LoadPhotoAsync(string officialId, CancellationToken ct)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return;
        var url = $"{creds.BackendUrl.TrimEnd('/')}/api/public/officials/{officialId}/photo.jpg";
        byte[] bytes;
        try
        {
            using var resp = await _http.GetAsync(url, ct).ConfigureAwait(false);
            if (!resp.IsSuccessStatusCode) return;
            bytes = await resp.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        }
        catch
        {
            return;
        }
        if (bytes.Length == 0 || ct.IsCancellationRequested) return;
        _photoCache[officialId] = bytes;

        // Bitmap construction has to happen on the UI thread (Avalonia
        // resources are thread-affine). Marshal back.
        await Dispatcher.UIThread.InvokeAsync(() =>
        {
            if (ct.IsCancellationRequested) return;
            // Re-check that the bound Official hasn't changed underneath
            // us — a fast scroll could have swapped to a different
            // person before our await returned.
            if (Official?.Id != officialId) return;
            try
            {
                using var ms = new MemoryStream(bytes);
                PhotoImage.Source = new Bitmap(ms);
                PhotoFrame.IsVisible = true;
                FallbackCircle.IsVisible = false;
            }
            catch { /* corrupt bytes — leave initials up */ }
        });
    }

    private void ShowInitials(string text, bool isChief)
    {
        Initials.Text = text;
        // Chief gets the amber accent; deputies stay on deep blue —
        // matches the home tile colours so the role connection is
        // visually obvious.
        FallbackCircle.Background = isChief
            ? (IBrush)(Application.Current!.Resources["KioskAccentDark"] ?? Brushes.Goldenrod)
            : (IBrush)(Application.Current!.Resources["KioskPrimary"] ?? Brushes.SteelBlue);
        FallbackCircle.IsVisible = true;
        PhotoFrame.IsVisible = false;
    }

    private static string InitialsFor(string name)
    {
        if (string.IsNullOrWhiteSpace(name)) return "?";
        var parts = name.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 0) return "?";
        if (parts.Length == 1) return parts[0].Substring(0, 1).ToUpperInvariant();
        return (parts[0].Substring(0, 1) + parts[1].Substring(0, 1)).ToUpperInvariant();
    }
}
