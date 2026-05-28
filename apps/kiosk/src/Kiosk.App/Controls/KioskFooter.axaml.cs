using Avalonia.Controls;
using Avalonia.Interactivity;
using Kiosk.App.Localization;
using Kiosk.App.State;

namespace Kiosk.App.Controls;

/// <summary>Deep-blue footer band with the 3-language toggle on the left
/// and the org's helpline phone on the right. The toggle moved here
/// from the header in the 2026 redesign — header is for branding only
/// now. Active button class is driven by the LocalizationService.LanguageChanged
/// event so the visual state matches the actual loaded dictionary.</summary>
public partial class KioskFooter : UserControl
{
    public KioskFooter()
    {
        InitializeComponent();
        DataContext = SessionStore.Current;
        Loaded += (_, _) =>
        {
            LocalizationService.LanguageChanged += OnLanguageChanged;
            UpdateActiveLangClass(LocalizationService.Current);
        };
        Unloaded += (_, _) =>
        {
            LocalizationService.LanguageChanged -= OnLanguageChanged;
        };
    }

    private void OnLanguageChanged(Language lang) =>
        Avalonia.Threading.Dispatcher.UIThread.Post(() => UpdateActiveLangClass(lang));

    private void UpdateActiveLangClass(Language lang)
    {
        SetActive(LangKkBtn, lang == Language.Kk);
        SetActive(LangUzBtn, lang == Language.Uz);
        SetActive(LangRuBtn, lang == Language.Ru);
    }

    private static void SetActive(Button btn, bool active)
    {
        if (active) { if (!btn.Classes.Contains("active")) btn.Classes.Add("active"); }
        else { btn.Classes.Remove("active"); }
    }

    private void OnLangKk(object? sender, RoutedEventArgs e) =>
        LocalizationService.SetLanguage(Language.Kk);
    private void OnLangUz(object? sender, RoutedEventArgs e) =>
        LocalizationService.SetLanguage(Language.Uz);
    private void OnLangRu(object? sender, RoutedEventArgs e) =>
        LocalizationService.SetLanguage(Language.Ru);
}
