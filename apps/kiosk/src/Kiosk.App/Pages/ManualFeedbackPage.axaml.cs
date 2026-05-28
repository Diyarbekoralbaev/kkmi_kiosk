using System;
using System.ComponentModel;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>Touch-driven feedback flow. Visitor moves through
/// type → text → phone → preview → success without using voice. The
/// type is one of complaint / suggestion / gratitude; the text is the
/// custom on-screen keyboard; phone uses the NumericKeypad. Backend
/// POST /api/kiosk/feedback is the only network call.
///
/// Modeled on <see cref="ManualSubmitPage"/>. Reuses the SessionStore
/// feedback fields (FeedbackType / FeedbackText / FeedbackPhone /
/// FeedbackSubmittedId / ShowFeedbackSuccess) and its own step enum
/// (<see cref="ManualFeedbackStep"/>) so the voice flow can't drive this
/// page's visibility.</summary>
public partial class ManualFeedbackPage : UserControl
{
    private const string EmptyPhoneFormat = "+998 __ - ___ - __ - __";

    private bool _keyboardsWired;
    // Re-entrancy guard: PhoneBox.Text = formatted inside OnPhoneTextChanged
    // re-fires TextChanged. Mirror of ManualSubmitPage's _formattingPhone.
    private bool _formattingPhone;
    private DispatcherTimer? _successDismissTimer;

    public ManualFeedbackPage()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        SessionStore.Current.PropertyChanged += OnStateChanged;
    }

    private void OnLoaded(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        // Fresh start every entry — wipe whatever the voice flow may have
        // populated and reset to step 1 (type).
        s.FeedbackType = "";
        s.FeedbackText = "";
        s.FeedbackPhone = "";
        s.FeedbackSubmittedId = "";
        s.ShowFeedbackSuccess = false;
        s.ManualFeedbackStep = ManualFeedbackStep.Type;
        PhoneBox.Text = EmptyPhoneFormat;

        if (!_keyboardsWired)
        {
            TextKeyboard.TargetTextBox = TextBox;
            TextKeyboard.Cleared += (_, _) =>
            {
                SessionStore.Current.FeedbackText = "";
                TextStatus.IsVisible = false;
            };
            PhoneKeypad.TargetTextBox = PhoneBox;
            PhoneKeypad.Cleared += (_, _) => PhoneBox.Text = EmptyPhoneFormat;
            PhoneBox.TextChanged += OnPhoneTextChanged;
            _keyboardsWired = true;
        }

        TextStatus.IsVisible = false;
        PhoneStatus.IsVisible = false;
        PreviewStatus.IsVisible = false;
        UpdateVisibility();
    }

    private void OnUnloaded(object? sender, RoutedEventArgs e)
    {
        _successDismissTimer?.Stop();
        _successDismissTimer = null;
    }

    private void OnStateChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.ManualFeedbackStep)
            || e.PropertyName == nameof(SessionStore.ShowFeedbackSuccess))
        {
            Dispatcher.UIThread.Post(UpdateVisibility);
        }
    }

    private void UpdateVisibility()
    {
        var s = SessionStore.Current;
        var showSuccess = s.ShowFeedbackSuccess;
        SectionType.IsVisible = !showSuccess && s.ManualFeedbackStep == ManualFeedbackStep.Type;
        SectionText.IsVisible = !showSuccess && s.ManualFeedbackStep == ManualFeedbackStep.Text;
        SectionPhone.IsVisible = !showSuccess && s.ManualFeedbackStep == ManualFeedbackStep.Phone;
        SectionPreview.IsVisible = !showSuccess && s.ManualFeedbackStep == ManualFeedbackStep.Preview;
        SectionSuccess.IsVisible = showSuccess;

        if (SectionPreview.IsVisible)
        {
            PreviewType.Text = TypeLabel(s.FeedbackType);
            PreviewText.Text = s.FeedbackText ?? "";
            PreviewPhone.Text = FormatPhonePretty(s.FeedbackPhone ?? "");
        }
        if (showSuccess)
        {
            SuccessIdText.Text = string.IsNullOrEmpty(s.FeedbackSubmittedId)
                ? ""
                : string.Format(
                    LocalizationService.Get("ManualMurajatSuccessId"),
                    ShortenId(s.FeedbackSubmittedId));
            StartSuccessDismissTimer();
        }
    }

    private static string TypeLabel(string type) => type switch
    {
        "complaint" => LocalizationService.Get("FeedbackTypeComplaint"),
        "suggestion" => LocalizationService.Get("FeedbackTypeSuggestion"),
        "gratitude" => LocalizationService.Get("FeedbackTypeGratitude"),
        _ => "",
    };

    // ── Type ────────────────────────────────────────────────────────

    private void OnTypeComplaint(object? sender, RoutedEventArgs e) => PickType("complaint");
    private void OnTypeSuggestion(object? sender, RoutedEventArgs e) => PickType("suggestion");
    private void OnTypeGratitude(object? sender, RoutedEventArgs e) => PickType("gratitude");

    private void PickType(string type)
    {
        SessionStore.Current.FeedbackType = type;
        SessionStore.Current.ManualFeedbackStep = ManualFeedbackStep.Text;
    }

    // ── Text ────────────────────────────────────────────────────────

    private void OnTextBack(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.ManualFeedbackStep = ManualFeedbackStep.Type;
    }

    private void OnTextContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var text = (s.FeedbackText ?? "").Trim();
        if (text.Length < 5)
        {
            TextStatus.IsVisible = true;
            return;
        }
        s.FeedbackText = text;
        TextStatus.IsVisible = false;
        s.ManualFeedbackStep = ManualFeedbackStep.Phone;
    }

    // ── Phone ───────────────────────────────────────────────────────

    private void OnPhoneTextChanged(object? sender, TextChangedEventArgs e)
    {
        if (PhoneBox is null) return;
        if (_formattingPhone) return;
        _formattingPhone = true;
        try
        {
            PhoneBox.Text = FormatPhone(PhoneBox.Text ?? "");
            PhoneBox.CaretIndex = (PhoneBox.Text ?? "").Length;
        }
        finally { _formattingPhone = false; }
    }

    private static string FormatPhone(string raw)
    {
        var digits = new string(raw.Where(char.IsDigit).ToArray());
        if (digits.StartsWith("998")) digits = digits[3..];
        if (digits.Length > 9) digits = digits[..9];
        var p = digits.PadRight(9, '_');
        return $"+998 {p[0]}{p[1]} - {p[2]}{p[3]}{p[4]} - {p[5]}{p[6]} - {p[7]}{p[8]}";
    }

    private static string ExtractPhoneDigits(string raw)
    {
        var digits = new string(raw.Where(char.IsDigit).ToArray());
        if (digits.StartsWith("998")) digits = digits[3..];
        return digits;
    }

    private static string FormatPhonePretty(string e164)
    {
        var d = ExtractPhoneDigits(e164);
        if (d.Length == 12 && d.StartsWith("998")) d = d.Substring(3);
        if (d.Length != 9) return e164;
        return $"+998 {d[0]}{d[1]} - {d[2]}{d[3]}{d[4]} - {d[5]}{d[6]} - {d[7]}{d[8]}";
    }

    private void OnPhoneBack(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.ManualFeedbackStep = ManualFeedbackStep.Text;
    }

    private void OnPhoneContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var digits = ExtractPhoneDigits(PhoneBox.Text ?? "");
        if (digits.Length != 9)
        {
            PhoneStatus.IsVisible = true;
            return;
        }
        s.FeedbackPhone = "+998" + digits;
        PhoneStatus.IsVisible = false;
        s.ManualFeedbackStep = ManualFeedbackStep.Preview;
    }

    // ── Preview / Submit ────────────────────────────────────────────

    private void OnPreviewEdit(object? sender, RoutedEventArgs e)
    {
        // Send the visitor back to the type step. Text and phone are preserved.
        SessionStore.Current.ManualFeedbackStep = ManualFeedbackStep.Type;
    }

    private async void OnPreviewConfirm(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var type = (s.FeedbackType ?? "").Trim();
        var text = (s.FeedbackText ?? "").Trim();
        var phone = (s.FeedbackPhone ?? "").Trim();
        if (type.Length == 0 || text.Length < 5 || ExtractPhoneDigits(phone).Length != 9)
        {
            PreviewStatus.IsVisible = true;
            return;
        }

        SubmitButton.IsEnabled = false;
        PreviewStatus.Foreground = Avalonia.Media.Brushes.SlateGray;
        PreviewStatus.Text = LocalizationService.Get("ManualMurajatSubmitting");
        PreviewStatus.IsVisible = true;

        var result = await KioskApi.CreateFeedbackAsync(type, text, phone);
        if (result is null)
        {
            PreviewStatus.Foreground = Avalonia.Media.Brush.Parse("#dc2626");
            PreviewStatus.Text = LocalizationService.Get("ManualMurajatSubmitError");
            SubmitButton.IsEnabled = true;
            return;
        }

        s.FeedbackSubmittedId = result.FeedbackId;
        s.ShowFeedbackSuccess = true;
        s.ManualFeedbackStep = ManualFeedbackStep.Done;
    }

    // ── Success auto-dismiss ───────────────────────────────────────

    private void StartSuccessDismissTimer()
    {
        _successDismissTimer?.Stop();
        _successDismissTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(6) };
        _successDismissTimer.Tick += (_, _) =>
        {
            _successDismissTimer?.Stop();
            SessionStore.Current.ResetIdle();
        };
        _successDismissTimer.Start();
    }

    private static string ShortenId(string id) =>
        string.IsNullOrEmpty(id) || id.Length < 8 ? id : id.Substring(0, 8);
}
