using System;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Kiosk.App.Identity;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.Print;
using Kiosk.App.Settings;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>Joqarı Keńes reception-registration flow on a single screen.
/// No officials, no scheduled date — the citizen leaves an (optional)
/// topic + a phone, and the Council calls them back. Sections:
/// (A) topic (skippable) → (B) phone keypad → (B2) phone confirm →
/// (B3) voice-flow preview → (C) success talon. State is driven by
/// SessionStore so the voice and manual flows share the view — when the
/// voice agent populates AppointmentStep/Topic/Phone, the same sections
/// react. On manual confirm we POST /api/kiosk/appointments(phone, topic)
/// then auto-print the receipt PDF if AutoPrintReceipts is on.</summary>
public partial class QabulPage : UserControl
{
    // After a successful registration the talon stays on screen for this
    // long, then we auto-bounce back to Home and wipe the state.
    private static readonly TimeSpan SuccessAutoDismiss = TimeSpan.FromSeconds(8);
    private DispatcherTimer? _successDismissTimer;
    // QabulPage is cached + re-Loaded — without this guard the closure
    // would be hooked N times after N visits and clearing the phone box
    // would fire N times per ✕ tap.
    private bool _keypadWired;
    // Re-entrancy guard for the phone-formatting TextChanged handler.
    private bool _formattingPhone;
    // True while the visitor is on the phone-preview confirmation step.
    private bool _phonePreviewShown;
    // True after the visitor leaves the topic step (typed Continue OR
    // tapped Skip OR the voice flow already populated a topic). Drives
    // section visibility forward into the phone step.
    private bool _topicConfirmed;
    private const string EmptyPhoneFormat = "+998 __ - ___ - __ - __";

    public QabulPage()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            // QabulPage instances are cached by SessionStore.CurrentView, so
            // Loaded fires every time the page becomes visible. The
            // idempotent -= / += pair below stops the handlers stacking.
            SessionStore.Current.PropertyChanged -= OnSessionChanged;
            SessionStore.Current.PropertyChanged += OnSessionChanged;
            // Talon labels are <Run>s — Avalonia doesn't track DynamicResource
            // on Run.Text well across language swaps, so we set them in
            // code-behind and re-set on LanguageChanged.
            LocalizationService.LanguageChanged -= OnLanguageChanged;
            LocalizationService.LanguageChanged += OnLanguageChanged;
            RefreshTalonLabels();

            if (!SessionStore.Current.ShowAppointmentSuccess)
                WipeAppointmentState();

            _phonePreviewShown = false;
            UpdateVisibility();
            UpdateQrImage();
            if (SessionStore.Current.ShowAppointmentSuccess)
                StartSuccessDismissTimer();

            if (!_keypadWired)
            {
                Keypad.TargetTextBox = PhoneBox;
                Keypad.Cleared += (_, _) => PhoneBox.Text = EmptyPhoneFormat;
                PhoneBox.TextChanged += OnPhoneTextChanged;
                // Topic step — bind the on-screen keyboard to the topic
                // TextBox. Cleared wipes the topic so the empty state shows.
                TopicKeyboard.TargetTextBox = TopicBox;
                TopicKeyboard.Cleared += (_, _) =>
                    SessionStore.Current.AppointmentTopic = "";
                _keypadWired = true;
            }
            PhoneBox.Text = EmptyPhoneFormat;
        };
        Unloaded += (_, _) =>
        {
            SessionStore.Current.PropertyChanged -= OnSessionChanged;
            LocalizationService.LanguageChanged -= OnLanguageChanged;
            _successDismissTimer?.Stop();
            _successDismissTimer = null;
            if (SessionStore.Current.ShowAppointmentSuccess)
                WipeAppointmentState();
            _phonePreviewShown = false;
        };
    }

    private void OnLanguageChanged(Language _) =>
        Dispatcher.UIThread.Post(RefreshTalonLabels);

    private void RefreshTalonLabels()
    {
        TalonLabelReference.Text = LocalizationService.Get("QabulTalonReference");
        TalonLabelMasala.Text = LocalizationService.Get("QabulTalonMasala");
        TalonLabelTelefon.Text = LocalizationService.Get("QabulTalonTelefon");
    }

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        // AppointmentTopic is intentionally NOT in this list — the TopicBox
        // two-way-binds to it, so reacting on every keystroke would flip the
        // section away from the topic step on the first character typed.
        if (e.PropertyName == nameof(SessionStore.ShowAppointmentSuccess)
            || e.PropertyName == nameof(SessionStore.AppointmentStep)
            || e.PropertyName == nameof(SessionStore.AppointmentPhoneMasked))
        {
            Dispatcher.UIThread.Post(UpdateVisibility);
            if (e.PropertyName == nameof(SessionStore.ShowAppointmentSuccess)
                && SessionStore.Current.ShowAppointmentSuccess)
            {
                Dispatcher.UIThread.Post(StartSuccessDismissTimer);
            }
        }
        if (e.PropertyName == nameof(SessionStore.AppointmentQrPng))
            Dispatcher.UIThread.Post(UpdateQrImage);
    }

    private void StartSuccessDismissTimer()
    {
        _successDismissTimer?.Stop();
        _successDismissTimer = new DispatcherTimer { Interval = SuccessAutoDismiss };
        _successDismissTimer.Tick += (_, _) =>
        {
            _successDismissTimer?.Stop();
            _successDismissTimer = null;
            WipeAppointmentState();
            SessionStore.Current.Navigate(KioskPage.Home);
        };
        _successDismissTimer.Start();
    }

    private void WipeAppointmentState()
    {
        var s = SessionStore.Current;
        s.AppointmentStep = AppointmentStep.Idle;
        s.AppointmentTopic = "";
        s.AppointmentPhoneMasked = "";
        s.AppointmentVerificationUrl = "";
        s.AppointmentId = "";
        s.AppointmentReferenceNo = "";
        s.AppointmentQrPng = null;
        s.AppointmentReceiptPdf = null;
        s.ShowAppointmentSuccess = false;
        PhoneBox.Text = EmptyPhoneFormat;
        ConfirmStatus.IsVisible = false;
        ConfirmButton.IsEnabled = true;
        PhonePreviewStatus.IsVisible = false;
        _phonePreviewShown = false;
        // Voice flow may pre-populate the topic via appointment_progress;
        // if it did, skip the manual topic step on this entry.
        _topicConfirmed = !string.IsNullOrWhiteSpace(s.AppointmentTopic);
    }

    private void UpdateVisibility()
    {
        var s = SessionStore.Current;
        // Voice-flow preview kicks in when the AI agent has called
        // preview_appointment (AppointmentStep == Preview) and we're not
        // already in the manual phone-preview path.
        var voicePreviewActive =
            !s.ShowAppointmentSuccess && !_phonePreviewShown
            && s.AppointmentStep == AppointmentStep.Preview;

        SectionEnterTopic.IsVisible =
            !s.ShowAppointmentSuccess && !_topicConfirmed
            && !_phonePreviewShown && !voicePreviewActive;
        SectionEnterPhone.IsVisible =
            !s.ShowAppointmentSuccess && _topicConfirmed
            && !_phonePreviewShown && !voicePreviewActive;
        SectionPhonePreview.IsVisible = !s.ShowAppointmentSuccess && _phonePreviewShown;
        SectionVoicePreview.IsVisible = voicePreviewActive;
        SectionSuccess.IsVisible = s.ShowAppointmentSuccess;

        if (voicePreviewActive)
        {
            VoicePreviewTopic.Text = s.AppointmentTopic ?? "";
            VoicePreviewPhone.Text = s.AppointmentPhoneMasked ?? "";
        }
        if (s.ShowAppointmentSuccess)
            TalonOrgName.Text = (s.OrgName ?? "").ToUpperInvariant();
    }

    private async void OnVoicePreviewConfirm(object? sender, RoutedEventArgs e)
    {
        // Forward the affirmative as a user_text turn — backend wraps it
        // with turnComplete and Gemini reacts naturally (typically by
        // calling submit_appointment with the same args from the preview).
        if (KioskRuntime.Current is not null)
            await KioskRuntime.Current.SendUserTextAsync("awa, tasdıqlayman");
    }

    private async void OnVoicePreviewReject(object? sender, RoutedEventArgs e)
    {
        if (KioskRuntime.Current is not null)
            await KioskRuntime.Current.SendUserTextAsync("yoq, qaytarıń");
    }

    private void UpdateQrImage()
    {
        var bytes = SessionStore.Current.AppointmentQrPng;
        if (bytes is null || bytes.Length == 0)
        {
            QrImage.Source = null;
            return;
        }
        using var ms = new MemoryStream(bytes);
        QrImage.Source = new Bitmap(ms);
    }

    /// <summary>Topic step — optional issue summary. Continue requires a
    /// minimum length so a half-typed line doesn't get sent; the visitor
    /// can always Skip to leave it blank.</summary>
    private void OnTopicContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        s.AppointmentTopic = (s.AppointmentTopic ?? "").Trim();
        _topicConfirmed = true;
        UpdateVisibility();
    }

    private void OnTopicSkip(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.AppointmentTopic = "";
        _topicConfirmed = true;
        UpdateVisibility();
    }

    private void OnEditTopic(object? sender, RoutedEventArgs e)
    {
        // Back to the topic step from the phone keypad.
        _topicConfirmed = false;
        UpdateVisibility();
    }

    private void OnPhoneTextChanged(object? sender, TextChangedEventArgs e)
    {
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

    private static string ExtractPhoneDigits(string formatted)
    {
        var digits = new string(formatted.Where(char.IsDigit).ToArray());
        if (digits.StartsWith("998")) digits = digits[3..];
        return digits;
    }

    /// <summary>Pressing "Tastıyıqlaw" on the keypad screen doesn't submit
    /// — it transitions to the preview/confirmation step. Submission only
    /// happens after the visitor reviews the formatted phone and taps
    /// "Awa, jiberiw". This catches digit typos before they go to the
    /// backend.</summary>
    private void OnGoToPhonePreview(object? sender, RoutedEventArgs e)
    {
        var phone = ExtractPhoneDigits(PhoneBox.Text ?? "");
        if (phone.Length != 9)
        {
            ConfirmStatus.Text = LocalizationService.Get("QabulConfirmErrorPhoneShort");
            ConfirmStatus.IsVisible = true;
            return;
        }
        ConfirmStatus.IsVisible = false;
        PhonePreviewText.Text = PhoneBox.Text;
        PhonePreviewStatus.IsVisible = false;
        ConfirmButton.IsEnabled = true;
        _phonePreviewShown = true;
        UpdateVisibility();
    }

    private void OnPhoneEdit(object? sender, RoutedEventArgs e)
    {
        // Back to the keypad — the phone stays in the box so visitor can
        // fix one digit instead of re-entering all 9.
        _phonePreviewShown = false;
        UpdateVisibility();
    }

    private async void OnConfirmClicked(object? sender, RoutedEventArgs e)
    {
        var phone = ExtractPhoneDigits(PhoneBox.Text ?? "");
        if (phone.Length != 9)
        {
            PhonePreviewStatus.Text = LocalizationService.Get("QabulConfirmErrorPhoneShort");
            PhonePreviewStatus.IsVisible = true;
            return;
        }

        ConfirmButton.IsEnabled = false;
        PhonePreviewStatus.Foreground = Avalonia.Media.Brushes.SlateGray;
        PhonePreviewStatus.Text = LocalizationService.Get("QabulConfirmSending");
        PhonePreviewStatus.IsVisible = true;

        var topic = (SessionStore.Current.AppointmentTopic ?? "").Trim();
        var result = await KioskApi.CreateAppointmentAsync("+998" + phone, topic);
        if (result is null)
        {
            PhonePreviewStatus.Foreground = Avalonia.Media.Brush.Parse("#dc2626");
            PhonePreviewStatus.Text = LocalizationService.Get("QabulConfirmError");
            ConfirmButton.IsEnabled = true;
            return;
        }

        var s = SessionStore.Current;
        s.AppointmentId = result.AppointmentId;
        s.AppointmentReferenceNo = result.ReferenceNo;
        s.AppointmentPhoneMasked = result.PhoneMasked;
        // QR is embedded in the POST response so the on-screen talon shows
        // the same identifier the printed receipt does.
        try
        {
            s.AppointmentQrPng = string.IsNullOrEmpty(result.QrPngBase64)
                ? null
                : Convert.FromBase64String(result.QrPngBase64);
        }
        catch (Exception ex)
        {
            s.AppointmentQrPng = null;
            Console.Error.WriteLine(
                $"[appointment] manual-flow QR decode failed: {ex.GetType().Name}: {ex.Message} (input_len={result.QrPngBase64.Length})");
        }
        // Refresh the org-branding bundle from the response — catches a
        // super-admin rename that landed since the last heartbeat. No-op on
        // older backends that ship an empty translations dict.
        if (result.OrgNameTranslations is not null && result.OrgNameTranslations.Count > 0)
        {
            s.UpdateOrgBranding(result.OrgNameTranslations,
                string.IsNullOrEmpty(s.OrgName) ? "" : s.OrgName);
        }
        s.ShowAppointmentSuccess = true;

        _ = PrintReceiptAsync(result.VerificationToken);
    }

    private static async Task PrintReceiptAsync(string verificationToken)
    {
        if (!KioskSettings.Current.AutoPrintReceipts) return;
        if (string.IsNullOrEmpty(verificationToken)) return;
        try
        {
            var creds = DeviceKeyStore.Load();
            if (creds is null) return;
            // Pass the kiosk's current UI language so the printed receipt
            // matches what's on screen.
            var lang = LocalizationService.LangCode(LocalizationService.Current);
            var url = $"{creds.BackendUrl.TrimEnd('/')}/api/public/appointments/receipt/{verificationToken}.pdf?lang={lang}";
            using var http = PinnedHttpClient.Create();
            var bytes = await http.GetByteArrayAsync(url);
            if (bytes.Length == 0) return;
            await ReceiptPrinter.PrintAsync(bytes, KioskSettings.Current.PrinterName);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[print] receipt failed: {ex.Message}");
        }
    }
}
