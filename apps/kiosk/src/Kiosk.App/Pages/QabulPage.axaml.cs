using System;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Net.Http;
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

/// <summary>Manual booking flow on a single screen with four sections:
/// (A) officials picker — chief hero + deputies grid, (B) phone keypad,
/// (B2) phone preview / confirmation, (C) success talon. State is
/// driven by SessionStore so voice flow and manual flow share the same
/// view — when voice updates AppointmentOfficialId, the manual UI moves
/// to the phone step automatically; when voice flips
/// ShowAppointmentSuccess, the talon renders. On manual confirm we
/// POST /api/kiosk/appointments (no topic), then auto-print the receipt
/// PDF if AutoPrintReceipts is on.</summary>
public partial class QabulPage : UserControl
{
    // After a successful booking the talon stays on screen for this long,
    // then we auto-bounce back to Home and wipe the appointment state.
    private static readonly TimeSpan SuccessAutoDismiss = TimeSpan.FromSeconds(5);
    private DispatcherTimer? _successDismissTimer;
    // QabulPage is cached + re-Loaded — without this guard the closure
    // would be hooked N times after N visits and clearing the phone box
    // would fire N times per ✕ tap.
    private bool _keypadWired;
    // Re-entrancy guard for the phone-formatting TextChanged handler.
    private bool _formattingPhone;
    // True while the visitor is on the phone-preview confirmation step.
    // Drives section visibility; reset by every OnPickAnother / Loaded.
    private bool _phonePreviewShown;
    // True after the visitor explicitly presses the topic-step Continue
    // button. Drives section visibility — must NOT depend on
    // AppointmentTopic length, because the TextBox's two-way binding
    // would set length>0 on the first keystroke and flip us into the
    // phone section mid-typing. Reset by WipeAppointmentState +
    // OnPickAnother. Pre-set to true in OnOfficialClicked when voice
    // flow has already populated topic (skip the manual step).
    private bool _topicConfirmed;
    private const string EmptyPhoneFormat = "+998 __ - ___ - __ - __";

    public QabulPage()
    {
        InitializeComponent();
        Loaded += async (_, _) =>
        {
            // QabulPage instances are cached by SessionStore.CurrentView, so
            // Loaded fires every time the page becomes visible after a
            // Navigate(...). Without the idempotent -= / += pair below, each
            // re-entry would stack another subscription on the same handler,
            // and OnSessionChanged would fire 2× / 3× / ... per property
            // change.
            SessionStore.Current.PropertyChanged -= OnSessionChanged;
            SessionStore.Current.PropertyChanged += OnSessionChanged;
            // Talon labels ("Mansabdor:", "Sana:", …) are <Run>s — Avalonia
            // doesn't track DynamicResource on Run.Text well across language
            // swaps, so we set them in code-behind and re-set on
            // LanguageChanged. Idempotent -= / += same as the property
            // subscription above.
            LocalizationService.LanguageChanged -= OnLanguageChanged;
            LocalizationService.LanguageChanged += OnLanguageChanged;
            RefreshTalonLabels();

            // Clear filter-dependent state BEFORE awaiting the officials
            // fetch. See feedback comment for the "deputies → 4 → 1 flash"
            // bug that prompted this pattern.
            var roleFilter = SessionStore.Current.QabulRoleFilter;
            QabulTitleText.Text = roleFilter switch
            {
                "chief" => LocalizationService.Get("QabulPageTitleChief"),
                "deputy" => LocalizationService.Get("QabulPageTitleDeputy"),
                _ => LocalizationService.Get("QabulPageTitle"),
            };
            // Prompt also adapts so chief-only screens don't say "pick whom".
            QabulPickPromptText.Text = roleFilter switch
            {
                "chief" => LocalizationService.Get("QabulPickPromptChief"),
                "deputy" => LocalizationService.Get("QabulPickPromptDeputy"),
                _ => LocalizationService.Get("QabulPickPrompt"),
            };
            ChiefList.ItemsSource = null;
            DeputyList.ItemsSource = null;

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
                // New manual topic step — bind the on-screen keyboard
                // to the topic TextBox. Cleared = visitor wants to wipe
                // and start over from the picker (mirrors phone keypad
                // behavior). Setting AppointmentTopic = "" surfaces the
                // empty-topic validation on Continue.
                TopicKeyboard.TargetTextBox = TopicBox;
                TopicKeyboard.Cleared += (_, _) =>
                {
                    SessionStore.Current.AppointmentTopic = "";
                    TopicStatus.IsVisible = false;
                };
                _keypadWired = true;
            }
            PhoneBox.Text = EmptyPhoneFormat;

            var officials = await KioskApi.GetOfficialsAsync();
            roleFilter = SessionStore.Current.QabulRoleFilter;
            if (!string.IsNullOrEmpty(roleFilter))
                officials = officials.Where(o => string.Equals(o.Role, roleFilter, StringComparison.OrdinalIgnoreCase)).ToList();

            // Split chief vs deputy so the two ItemsControls render their
            // own layouts (hero vs grid). The agent flow (no role filter)
            // shows both lists so the agent's picks are visible too.
            var chiefs = officials.Where(o => string.Equals(o.Role, "chief", StringComparison.OrdinalIgnoreCase)).ToList();
            var deputies = officials.Where(o => !string.Equals(o.Role, "chief", StringComparison.OrdinalIgnoreCase)).ToList();
            ChiefList.ItemsSource = chiefs;
            ChiefList.IsVisible = chiefs.Count > 0;
            DeputyList.ItemsSource = deputies;
            DeputyList.IsVisible = deputies.Count > 0;
        };
        Unloaded += (_, _) =>
        {
            SessionStore.Current.PropertyChanged -= OnSessionChanged;
            LocalizationService.LanguageChanged -= OnLanguageChanged;
            _successDismissTimer?.Stop();
            _successDismissTimer = null;
            SessionStore.Current.QabulRoleFilter = "";
            if (SessionStore.Current.ShowAppointmentSuccess)
                WipeAppointmentState();
            _phonePreviewShown = false;
        };
    }

    private void OnLanguageChanged(Language _) =>
        Dispatcher.UIThread.Post(RefreshTalonLabels);

    private void RefreshTalonLabels()
    {
        // Same key naming as the backend's RECEIPT_STRINGS so on-screen
        // and printed talons stay in sync per language. Each value already
        // includes the trailing space — see kk/uz/ru.axaml entries.
        TalonLabelChipta.Text = LocalizationService.Get("QabulTalonChipta");
        TalonLabelMansabdor.Text = LocalizationService.Get("QabulTalonMansabdor");
        TalonLabelMasala.Text = LocalizationService.Get("QabulTalonMasala");
        TalonLabelSana.Text = LocalizationService.Get("QabulTalonSana");
        TalonLabelVaqt.Text = LocalizationService.Get("QabulTalonVaqt");
        TalonLabelNavbat.Text = LocalizationService.Get("QabulTalonNavbat");
        TalonLabelTelefon.Text = LocalizationService.Get("QabulTalonTelefon");
    }

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        // Voice-preview visibility depends on AppointmentStep crossing into
        // Preview, plus several fields whose mutation should refresh the
        // card (phone arrives last via OnAppointmentPreview, so we must
        // re-render once it lands or the card shows an empty phone slot).
        // AppointmentTopic is intentionally NOT in this list. The
        // TopicBox two-way-binds to it, so every keystroke would fire
        // PropertyChanged here. If UpdateVisibility ran on every
        // keystroke it would flip the section away from the topic
        // step on the first character typed and steal focus from the
        // visitor mid-word. The voice-flow preview card reads
        // AppointmentTopic at render time without needing this listener
        // — preview visibility is gated by AppointmentStep instead.
        if (e.PropertyName == nameof(SessionStore.AppointmentOfficialId)
            || e.PropertyName == nameof(SessionStore.ShowAppointmentSuccess)
            || e.PropertyName == nameof(SessionStore.AppointmentStep)
            || e.PropertyName == nameof(SessionStore.AppointmentPhoneMasked)
            || e.PropertyName == nameof(SessionStore.AppointmentScheduledDateHuman))
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
        s.AppointmentOfficialId = "";
        s.AppointmentOfficialName = "";
        s.AppointmentOfficialPosition = "";
        s.AppointmentScheduledDate = "";
        s.AppointmentScheduledDateHuman = "";
        s.AppointmentReceptionTime = "";
        s.AppointmentPhoneMasked = "";
        s.AppointmentVerificationUrl = "";
        s.AppointmentId = "";
        s.AppointmentQueueNumber = 0;
        s.AppointmentQrPng = null;
        s.AppointmentReceiptPdf = null;
        s.ShowAppointmentSuccess = false;
        PhoneBox.Text = EmptyPhoneFormat;
        ConfirmStatus.IsVisible = false;
        ConfirmButton.IsEnabled = true;
        PhonePreviewStatus.IsVisible = false;
        _phonePreviewShown = false;
        _topicConfirmed = false;
        TopicStatus.IsVisible = false;
        SelectedAvatar.Official = null;
    }

    private void UpdateVisibility()
    {
        var s = SessionStore.Current;
        var hasOfficial = !string.IsNullOrEmpty(s.AppointmentOfficialId);
        // Voice-flow preview kicks in when the AI agent has called
        // preview_appointment (AppointmentStep == Preview) and we're not
        // already in the manual phone-preview path. The manual flow's
        // _phonePreviewShown is mutually exclusive.
        var voicePreviewActive =
            !s.ShowAppointmentSuccess && hasOfficial && !_phonePreviewShown
            && s.AppointmentStep == AppointmentStep.Preview;
        // Manual topic step gates phone entry. Visitor sees the topic
        // textbox + keyboard after they pick an official and before the
        // phone keypad. `_topicConfirmed` flips only when the visitor
        // explicitly clicks the Continue button (OnTopicContinue) — we
        // do NOT check AppointmentTopic length here, otherwise typing
        // the first character would auto-flip the visibility and steal
        // the keyboard mid-keystroke. Voice flow may pre-populate
        // AppointmentTopic via the agent's appointment_progress tool
        // call; OnOfficialClicked picks that up by initialising
        // `_topicConfirmed = true` when topic is already present.
        SectionPickOfficial.IsVisible = !s.ShowAppointmentSuccess && !hasOfficial;
        SectionEnterTopic.IsVisible =
            !s.ShowAppointmentSuccess && hasOfficial && !_topicConfirmed
            && !_phonePreviewShown && !voicePreviewActive;
        SectionEnterPhone.IsVisible =
            !s.ShowAppointmentSuccess && hasOfficial && _topicConfirmed
            && !_phonePreviewShown && !voicePreviewActive;
        SectionPhonePreview.IsVisible = !s.ShowAppointmentSuccess && hasOfficial && _phonePreviewShown;
        SectionVoicePreview.IsVisible = voicePreviewActive;
        SectionSuccess.IsVisible = s.ShowAppointmentSuccess;

        // Mirror the official summary into the topic section's card so
        // visitors see who they picked while typing their issue. The
        // avatar's Official record is already set in OnOfficialClicked.
        if (SectionEnterTopic.IsVisible)
        {
            TopicSelectedName.Text = s.AppointmentOfficialName ?? "";
            TopicSelectedPosition.Text = s.AppointmentOfficialPosition ?? "";
        }
        if (voicePreviewActive)
        {
            // Populate preview card from the backend's appointment_preview
            // envelope, already mirrored into SessionStore by OnAppointmentPreview.
            VoicePreviewOfficialName.Text = s.AppointmentOfficialName ?? "";
            VoicePreviewOfficialPosition.Text = s.AppointmentOfficialPosition ?? "";
            VoicePreviewDate.Text = s.AppointmentScheduledDateHuman ?? "";
            VoicePreviewTime.Text = s.AppointmentReceptionTime ?? "";
            VoicePreviewPhone.Text = s.AppointmentPhoneMasked ?? "";
            VoicePreviewTopic.Text = s.AppointmentTopic ?? "";
        }
        if (s.ShowAppointmentSuccess)
        {
            // Mirror the printed receipt: uppercase org name header + a
            // role-specific subtitle below it.
            TalonOrgName.Text = (s.OrgName ?? "").ToUpperInvariant();
            TalonSubtitle.Text = LocalizationService.Get(
                string.Equals(s.AppointmentOfficialRole, "chief", StringComparison.OrdinalIgnoreCase)
                    ? "QabulTalonSubtitleChief"
                    : "QabulTalonSubtitleDeputy");
        }
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

    private void OnOfficialClicked(object? sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.DataContext is not Official ofc) return;
        var s = SessionStore.Current;
        s.AppointmentOfficialId = ofc.Id;
        s.AppointmentOfficialName = ofc.Name;
        s.AppointmentOfficialPosition = ofc.Position;
        s.AppointmentOfficialRole = ofc.Role;
        s.AppointmentReceptionTime = ofc.ReceptionTime;
        // Show the picked official's face on the topic + phone-entry
        // sections so the visitor never loses context for who they're
        // booking.
        SelectedAvatar.Official = ofc;
        TopicSelectedAvatar.Official = ofc;
        // Quick local hint with localized day name. Backend computes the
        // canonical date on submit and overrides this value.
        var dayLocalized = string.IsNullOrEmpty(ofc.ReceptionDay)
            ? ""
            : LocalizationService.FormatDay(ofc.ReceptionDay, LocalizationService.Current);
        s.AppointmentScheduledDateHuman = $"{dayLocalized} {ofc.ReceptionTime}".Trim();
        PhoneBox.Text = EmptyPhoneFormat;
        ConfirmStatus.IsVisible = false;
        ConfirmButton.IsEnabled = true;
        _phonePreviewShown = false;
        // If voice flow has already populated AppointmentTopic via the
        // agent's appointment_progress(stage='topic',...) call, skip the
        // manual topic step. Otherwise the manual entrant lands on the
        // topic step with an empty TextBox.
        _topicConfirmed = !string.IsNullOrWhiteSpace(s.AppointmentTopic);
        UpdateVisibility();
    }

    private void OnPickAnother(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        s.AppointmentOfficialId = "";
        s.AppointmentOfficialName = "";
        s.AppointmentOfficialPosition = "";
        s.AppointmentScheduledDateHuman = "";
        s.AppointmentReceptionTime = "";
        // Wipe topic too — visitor is restarting from the picker. If we
        // preserved it across re-picks, a new official would skip the
        // topic step (because _topicConfirmed would stay true) which is
        // confusing.
        s.AppointmentTopic = "";
        PhoneBox.Text = EmptyPhoneFormat;
        _phonePreviewShown = false;
        _topicConfirmed = false;
        TopicStatus.IsVisible = false;
        SelectedAvatar.Official = null;
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
    /// <summary>Manual topic step — visitor types their issue summary
    /// on the on-screen keyboard, then taps Continue. Validates length
    /// (min 3 chars after trim, max enforced by TextBox.MaxLength) and
    /// drives UpdateVisibility forward into the phone-entry section.
    /// </summary>
    private void OnTopicContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var topic = (s.AppointmentTopic ?? "").Trim();
        if (topic.Length < 3)
        {
            TopicStatus.IsVisible = true;
            return;
        }
        // Persist the trimmed value so the eventual API call sends a
        // clean string.
        s.AppointmentTopic = topic;
        TopicStatus.IsVisible = false;
        // Explicit Continue click is the ONLY thing that flips this — not
        // the TextBox length. That's the whole point of the flag.
        _topicConfirmed = true;
        UpdateVisibility();
    }

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
        var officialId = SessionStore.Current.AppointmentOfficialId;
        if (string.IsNullOrEmpty(officialId)) return;

        ConfirmButton.IsEnabled = false;
        PhonePreviewStatus.Foreground = Avalonia.Media.Brushes.SlateGray;
        PhonePreviewStatus.Text = LocalizationService.Get("QabulConfirmSending");
        PhonePreviewStatus.IsVisible = true;

        var topic = (SessionStore.Current.AppointmentTopic ?? "").Trim();
        var result = await KioskApi.CreateAppointmentAsync(officialId, phone, topic);
        if (result is null)
        {
            PhonePreviewStatus.Foreground = Avalonia.Media.Brush.Parse("#dc2626");
            PhonePreviewStatus.Text = LocalizationService.Get("QabulConfirmError");
            ConfirmButton.IsEnabled = true;
            return;
        }

        var s = SessionStore.Current;
        s.AppointmentId = result.AppointmentId;
        s.AppointmentQueueNumber = result.QueueNumber;
        s.AppointmentOfficialName = result.OfficialName;
        s.AppointmentOfficialPosition = result.OfficialPosition;
        s.AppointmentScheduledDate = result.ScheduledDate;
        s.AppointmentScheduledDateHuman = DateTime.TryParse(result.ScheduledDate, out var d)
            ? LocalizationService.FormatDate(d, LocalizationService.Current)
            : result.ScheduledDateHuman;
        s.AppointmentReceptionTime = result.ReceptionTime;
        s.AppointmentPhoneMasked = result.PhoneMasked;
        // Build the printed "Chipta raqami" string client-side so the
        // on-screen talon shows the same identifier the printed receipt
        // does (backend's render_receipt_pdf composes it the same way).
        s.AppointmentChiptaNumber = DateTime.TryParse(result.ScheduledDate, out var dd)
            ? $"O-{dd:yyyyMMdd}-{result.QueueNumber:000}"
            : "";
        // QR was missing on manual-flow talon for months because the HTTP
        // response (CreateAppointmentResponse) shipped no QR bytes, only the
        // WS voice envelope did. Backend now embeds qr_png_base64 in the
        // POST response — decode it here so <Image x:Name="QrImage" /> on
        // SectionSuccess actually has something to draw.
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
        // Refresh the org-branding bundle from the appointment response —
        // catches the case where a super-admin rename landed between this
        // kiosk's last heartbeat and now. No-op for older backends that
        // ship an empty translations dict.
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
            // matches what's on the screen — previously this always rendered
            // in Karakalpak (backend default) regardless of language.
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
