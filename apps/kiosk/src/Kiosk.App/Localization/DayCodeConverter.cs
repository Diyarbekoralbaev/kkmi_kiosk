using System;
using System.Globalization;
using Avalonia.Data.Converters;

namespace Kiosk.App.Localization;

/// <summary>XAML binding converter: ISO weekday code ("mon", "fri", ...) →
/// localized day name in the currently active kiosk language. Used by the
/// officials picker in QabulPage so each row shows "Juma" / "Пятница" /
/// "Жума" instead of the raw "fri" code that comes off the API.
///
/// Caveat: Avalonia doesn't re-run converters when an external observable
/// changes — flipping the language with this binding live will keep the
/// previously-rendered text until the source value changes (e.g. on next
/// page Loaded). Acceptable: language is normally picked once at session
/// start via the footer toggle, then the user stays in that language.
/// </summary>
public sealed class DayCodeConverter : IValueConverter
{
    public static readonly DayCodeConverter Instance = new();

    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is not string s || string.IsNullOrEmpty(s)) return "";
        return LocalizationService.FormatDay(s, LocalizationService.Current);
    }

    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => throw new NotSupportedException();
}
