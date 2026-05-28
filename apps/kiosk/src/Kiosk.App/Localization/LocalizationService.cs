using System;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Markup.Xaml.Styling;
using Kiosk.App.Settings;

namespace Kiosk.App.Localization;

public enum Language { Uz, Ru, Kk }

/// <summary>
/// Runtime language switcher. All 3 language ResourceDictionaries are
/// declared statically in <c>App.axaml</c>'s MergedDictionaries (mandatory
/// for AOT — runtime-constructed <see cref="ResourceInclude"/> gets
/// stripped by the trimmer and crashes with XamlLoadException). This service
/// switches the active language by REORDERING that pre-loaded list: Avalonia
/// resolves resources by walking MergedDictionaries in reverse, so the last
/// entry wins on a key collision. We just move the target language to the end.
///
/// AOT-safe: no runtime XAML loading.
/// </summary>
public static class LocalizationService
{
    public static Language Current { get; private set; } = Language.Uz;

    /// <summary>Fired after the active dictionary has been promoted. Subscribers
    /// that don't bind via DynamicResource (e.g. code-built strings, headers
    /// rendering org name dynamically) can refresh here.</summary>
    public static event Action<Language>? LanguageChanged;

    public static void SetLanguage(Language lang)
    {
        var app = Application.Current;
        if (app is null) return;

        var dicts = app.Resources.MergedDictionaries;
        var langCode = LangCode(lang);
        var sentinel = $"_Locale_{langCode}";

        // Find the dict that owns this language's sentinel key. We can't
        // rely on `d is ResourceInclude && d.Source.EndsWith(...)` because
        // the XAML compiler resolves ResourceInclude entries at compile time
        // and the runtime objects don't expose a stable Source. Querying
        // each dict for its unique sentinel key is reliable across whatever
        // the compiler produces.
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
            // No matching dict — App.axaml may have been edited inconsistently.
            // Quietly skip; UI stays on whatever order was declared.
            return;
        }

        // Move to end so it wins lookups. Avalonia walks MergedDictionaries
        // in reverse on key lookup, so the last entry has highest priority.
        dicts.Remove(target);
        dicts.Add(target);

        Current = lang;

        try
        {
            KioskSettings.Current.PreferredLanguage = langCode;
            KioskSettings.Current.Save();
        }
        catch { /* non-fatal — header stays in chosen language for this session */ }

        LanguageChanged?.Invoke(lang);
    }

    public static Language Parse(string? code) => code?.ToLowerInvariant() switch
    {
        "ru" => Language.Ru,
        "kk" => Language.Kk,
        _ => Language.Uz,
    };

    public static string LangCode(Language lang) => lang switch
    {
        Language.Ru => "ru",
        Language.Kk => "kk",
        _ => "uz",
    };

    /// <summary>Look up a localized string by key from the active resource
    /// dictionary. Useful for code-behind paths that can't bind via
    /// <c>{DynamicResource}</c> (e.g. inline status messages set on a
    /// TextBlock's Text property mid-flow). Falls back to the key itself
    /// so a missing translation surfaces in QA rather than silently blank.</summary>
    public static string Get(string key)
    {
        var app = Application.Current;
        if (app is null) return key;
        if (app.Resources.TryGetResource(key, null, out var value) && value is string s)
            return s;
        return key;
    }

    /// <summary>Localized day-of-week formatter. Backend returns ISO short
    /// codes ('mon','tue',…); the kiosk owns the display string per-language
    /// so we don't have to round-trip Accept-Language to the API.</summary>
    public static string FormatDay(string isoDay, Language lang) => (lang, isoDay?.ToLowerInvariant()) switch
    {
        (Language.Uz, "mon") => "Dushanba",
        (Language.Uz, "tue") => "Seshanba",
        (Language.Uz, "wed") => "Chorshanba",
        (Language.Uz, "thu") => "Payshanba",
        (Language.Uz, "fri") => "Juma",
        (Language.Uz, "sat") => "Shanba",
        (Language.Uz, "sun") => "Yakshanba",
        (Language.Ru, "mon") => "Понедельник",
        (Language.Ru, "tue") => "Вторник",
        (Language.Ru, "wed") => "Среда",
        (Language.Ru, "thu") => "Четверг",
        (Language.Ru, "fri") => "Пятница",
        (Language.Ru, "sat") => "Суббота",
        (Language.Ru, "sun") => "Воскресенье",
        // Karakalpak Cyrillic (default locale from 2026 redesign).
        (Language.Kk, "mon") => "Дүйшемби",
        (Language.Kk, "tue") => "Сейшемби",
        (Language.Kk, "wed") => "Сәршемби",
        (Language.Kk, "thu") => "Бейсемби",
        (Language.Kk, "fri") => "Жума",
        (Language.Kk, "sat") => "Шемби",
        (Language.Kk, "sun") => "Жексемби",
        _ => isoDay ?? "",
    };

    /// <summary>Date string for the kiosk header clock — "12-май, 2026-жыл"
    /// in Kk (Cyrillic), "12 мая 2026" in Ru, "12-may, 2026" in Uz.
    /// .NET's CultureInfo for kk-* renders Cyrillic but month names don't
    /// quite match the Karakalpak transliteration on Windows ICU builds,
    /// so we hand-roll the Kk variant.</summary>
    private static readonly string[] _monthsKk = {
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    };
    private static readonly string[] _monthsRu = {
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    };
    private static readonly string[] _monthsUz = {
        "yanvar", "fevral", "mart", "aprel", "may", "iyun",
        "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
    };

    public static string FormatDate(DateTime when, Language lang)
    {
        // Month index is 1-12 from DateTime.Month.
        var idx = when.Month - 1;
        return lang switch
        {
            Language.Ru => $"{when.Day} {_monthsRu[idx]} {when.Year}",
            Language.Uz => $"{when.Day}-{_monthsUz[idx]}, {when.Year}",
            _ => $"{when.Day}-{_monthsKk[idx]}, {when.Year}-жыл",
        };
    }
}
