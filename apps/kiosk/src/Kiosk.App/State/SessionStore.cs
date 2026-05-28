using System;
using System.Collections.ObjectModel;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using Kiosk.App.Net;
using Kiosk.App.Pages;
using Kiosk.App.Print;
using Kiosk.App.Settings;

namespace Kiosk.App.State;

public enum KioskPage
{
    Home,
    Submit,
    Contacts,
    Qabul,
    Ai,
    /// <summary>Manual touch-driven murojaat flow (NEW). Reached by
    /// tapping the Home Murajat tile. Distinct from the AI voice flow
    /// that the same SessionStore.Submit* fields used to drive — this
    /// page owns the keyboard-based topic + body + phone entry path.
    /// </summary>
    ManualSubmit,
    /// <summary>Touch-driven feedback flow (shaǵım / usınıs /
    /// minnetdarshılıq). Reached by tapping the Home Fikr tile, or by the
    /// voice agent navigating to "feedback".</summary>
    Feedback,
}

public enum SubmitStep
{
    Idle,
    Topic,
    Body,
    Phone,
    Review,
    Done,
}

public enum AppointmentStep
{
    Idle,
    Topic,
    Phone,
    Preview,
    Done,
}

/// <summary>State machine for the manual feedback page (touch flow, no
/// voice). Visitor: pick type → type text → enter phone → preview →
/// success. Kept separate from the submit/appointment steps so the
/// three flows can't drive each other's visibility.</summary>
public enum ManualFeedbackStep
{
    Idle,
    Type,
    Text,
    Phone,
    Preview,
    Done,
}

/// <summary>State machine for the manual murajaat page (touch flow,
/// no voice). Kept separate from <see cref="SubmitStep"/> so the AI
/// voice path can't accidentally drive the manual page's visibility
/// and vice versa — the two flows share the topic/body/phone fields
/// on SessionStore but read different step enums.</summary>
public enum ManualSubmitStep
{
    Idle,
    Topic,
    Body,
    Phone,
    Preview,
    Done,
}

/// <summary>
/// Observable singleton. Owned by MainWindow's DataContext. UI-thread only —
/// KioskRuntime marshals WS events through Dispatcher.UIThread before mutating it.
/// </summary>
public partial class SessionStore : ObservableObject
{
    public static SessionStore Current { get; } = new();

    private HomePage? _home;
    private SubmitPage? _submit;
    private ContactsPage? _contacts;
    private QabulPage? _qabul;
    private ManualSubmitPage? _manualSubmit;
    private ManualFeedbackPage? _manualFeedback;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CurrentView))]
    private KioskPage _currentPage = KioskPage.Home;

    [ObservableProperty] private ConnectionState _connectionState = ConnectionState.Disconnected;
    [ObservableProperty] private bool _showOfflineOverlay;

    /// <summary>True when backend rejected this device's key (revoked or unknown).
    /// UI flips to the "this kiosk needs re-enrollment" overlay instead of the
    /// transient offline one — they have very different operator actions.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowOfflineOverlay))]
    private bool _isRevoked;

    /// <summary>Tracks whether the user has STARTED the voice session via the MicOrb.
    /// The offline overlay is suppressed when voice is intentionally off — otherwise
    /// every Stop would briefly flash "Bayranıs joq" which is wrong UX.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowOfflineOverlay))]
    private bool _isVoiceActive;

    /// <summary>RMS of the last captured audio frame, normalized to [0, 1]. Drives the MicOrb pulse.</summary>
    [ObservableProperty] private float _inputLevel;
    /// <summary>True while the local VAD says the user is speaking. Drives the orb's "active" visual.</summary>
    [ObservableProperty] private bool _isSpeaking;

    [ObservableProperty] private SubmitStep _submitStep = SubmitStep.Idle;
    [ObservableProperty] private ManualSubmitStep _manualSubmitStep = ManualSubmitStep.Idle;
    [ObservableProperty] private string _submitTopic = "";
    [ObservableProperty] private string _submitBody = "";
    [ObservableProperty] private string _submitPhone = "";
    [ObservableProperty] private string _submittedId = "";
    [ObservableProperty] private bool _showSubmitSuccess;

    // ── Qabul (reception registration) state ───────────────────────────────
    // The Joqarı Keńes flow has NO official and NO scheduled date — the
    // citizen registers + leaves a phone (and optional topic) and the
    // Council calls them back. The talon shows a reference number + QR.
    [ObservableProperty] private AppointmentStep _appointmentStep = AppointmentStep.Idle;
    [ObservableProperty] private string _appointmentTopic = "";
    [ObservableProperty] private string _appointmentPhoneMasked = "";
    [ObservableProperty] private string _appointmentVerificationUrl = "";
    [ObservableProperty] private string _appointmentId = "";
    /// <summary>Human-readable reference number for the registration, e.g.
    /// "KK-20260528-0042". Shown on the on-screen talon and printed receipt.</summary>
    [ObservableProperty] private string _appointmentReferenceNo = "";
    [ObservableProperty] private byte[]? _appointmentQrPng;
    [ObservableProperty] private byte[]? _appointmentReceiptPdf;
    [ObservableProperty] private bool _showAppointmentSuccess;

    // ── Feedback (shaǵım / usınıs / minnetdarshılıq) state ──────────────────
    [ObservableProperty] private ManualFeedbackStep _manualFeedbackStep = ManualFeedbackStep.Idle;
    /// <summary>One of: "complaint", "suggestion", "gratitude".</summary>
    [ObservableProperty] private string _feedbackType = "";
    [ObservableProperty] private string _feedbackText = "";
    [ObservableProperty] private string _feedbackPhone = "";
    [ObservableProperty] private string _feedbackSubmittedId = "";
    [ObservableProperty] private bool _showFeedbackSuccess;

    [ObservableProperty] private string _liveTranscript = "";

    /// <summary>Org name shown in the header / talon. Hydrated from
    /// <c>DeviceCredentials.OrgName</c> at startup (persisted from the
    /// previous successful heartbeat), then refreshed on every heartbeat
    /// so a super-panel rename propagates without re-enrollment.
    /// Language-aware: <see cref="UpdateOrgBranding"/> recomputes this
    /// from <see cref="OrgNameTranslations"/> using
    /// <see cref="Localization.LocalizationService.Current"/>; the
    /// LanguageChanged subscription in the static constructor refreshes it
    /// when the visitor taps a language tile.</summary>
    [ObservableProperty] private string _orgName = "";

    /// <summary>Localized variants: {"uz": ..., "kk": ..., "ru": ...}. Driven
    /// by <see cref="UpdateOrgBranding"/>. The setter does NOT recompute
    /// <see cref="OrgName"/> on its own — callers always pair this with
    /// <see cref="UpdateOrgBranding"/> so the legacy fallback and the dict
    /// land atomically.</summary>
    [ObservableProperty] private System.Collections.Generic.Dictionary<string, string> _orgNameTranslations
        = new System.Collections.Generic.Dictionary<string, string>();

    /// <summary>Legacy single-string org name, kept around as the last-ditch
    /// fallback when <see cref="OrgNameTranslations"/> is empty or missing
    /// the active locale. Old backends that don't send translations land here.</summary>
    private string _orgNameFallback = "";

    /// <summary>Update the persisted-style org-branding bundle. Resolves
    /// <see cref="OrgName"/> from the dict against the current language,
    /// falling back to <paramref name="fallback"/> if no translation is
    /// available. Idempotent — safe to call from heartbeat + enroll paths
    /// or the LanguageChanged hook.</summary>
    public void UpdateOrgBranding(
        System.Collections.Generic.IReadOnlyDictionary<string, string>? translations,
        string fallback)
    {
        var dict = new System.Collections.Generic.Dictionary<string, string>();
        if (translations is not null)
        {
            foreach (var kvp in translations)
            {
                if (!string.IsNullOrWhiteSpace(kvp.Value))
                    dict[kvp.Key] = kvp.Value;
            }
        }
        _orgNameFallback = fallback ?? "";
        OrgNameTranslations = dict;
        OrgName = PickOrgName(dict, _orgNameFallback);
    }

    private static string PickOrgName(
        System.Collections.Generic.IReadOnlyDictionary<string, string> dict,
        string fallback)
    {
        var lang = Localization.LocalizationService.LangCode(
            Localization.LocalizationService.Current);
        if (dict.TryGetValue(lang, out var v) && !string.IsNullOrWhiteSpace(v))
            return v;
        // Try other supported locales before bailing to the legacy fallback.
        foreach (var code in new[] { "kk", "uz", "ru" })
        {
            if (dict.TryGetValue(code, out var alt) && !string.IsNullOrWhiteSpace(alt))
                return alt;
        }
        return fallback ?? "";
    }

    private void OnLocalizationLanguageChanged(Localization.Language _)
    {
        // Re-pick from the current translations bundle; null-safe if the
        // dict hasn't been populated yet.
        var dict = OrgNameTranslations ?? new System.Collections.Generic.Dictionary<string, string>();
        OrgName = PickOrgName(dict, _orgNameFallback);
        RefreshLocalizedContacts();
    }

    private SessionStore()
    {
        // Subscribed once for the lifetime of the app — SessionStore is a
        // process-wide singleton so we don't need to unsubscribe.
        Localization.LocalizationService.LanguageChanged += OnLocalizationLanguageChanged;
    }

    /// <summary>Localized weather widget text, e.g. "Нөкис · +25°". Filled
    /// from each heartbeat's `weather` payload (Open-Meteo via backend,
    /// 15-min cache). Empty string = hide the header weather row.</summary>
    [ObservableProperty] private string _weatherText = "";

    /// <summary>Per-org help-desk phone shown in the kiosk footer band.
    /// Empty = hide the help row (no per-org config yet).</summary>
    [ObservableProperty] private string _helplinePhone = "";

    /// <summary>Localized contact info bundles — driven by heartbeat (every
    /// 30 s) and the enroll response. Wire-format: {"uz": ..., "kk": ...,
    /// "ru": ...}. The single <c>OrgAddress</c>/<c>OrgWorkHours</c>
    /// projections below pick the active language; LanguageChanged
    /// re-picks them in lockstep with the org name.</summary>
    [ObservableProperty] private System.Collections.Generic.Dictionary<string, string> _orgAddressTranslations
        = new System.Collections.Generic.Dictionary<string, string>();

    [ObservableProperty] private System.Collections.Generic.Dictionary<string, string> _orgWorkHoursTranslations
        = new System.Collections.Generic.Dictionary<string, string>();

    /// <summary>Single email address shown on the Contacts page.</summary>
    [ObservableProperty] private string _orgEmail = "";

    /// <summary>Active-language address shown on the Contacts page row 1.</summary>
    [ObservableProperty] private string _orgAddress = "";

    /// <summary>Active-language work hours shown on the Contacts page row 4.</summary>
    [ObservableProperty] private string _orgWorkHours = "";

    /// <summary>Update the kiosk Contacts page contact bundle in one call.
    /// Called from heartbeat + enroll on the UI thread. Empty values are
    /// preserved as empty strings so the ContactsPage rows stay aligned
    /// rather than collapsing.</summary>
    public void UpdateContactInfo(
        System.Collections.Generic.IReadOnlyDictionary<string, string>? address,
        string email,
        System.Collections.Generic.IReadOnlyDictionary<string, string>? workHours,
        string helplinePhone)
    {
        OrgAddressTranslations = CopyDict(address);
        OrgWorkHoursTranslations = CopyDict(workHours);
        OrgEmail = email ?? "";
        HelplinePhone = helplinePhone ?? "";
        RefreshLocalizedContacts();
    }

    private static System.Collections.Generic.Dictionary<string, string> CopyDict(
        System.Collections.Generic.IReadOnlyDictionary<string, string>? src)
    {
        var dst = new System.Collections.Generic.Dictionary<string, string>();
        if (src is null) return dst;
        foreach (var kvp in src) dst[kvp.Key] = kvp.Value ?? "";
        return dst;
    }

    private void RefreshLocalizedContacts()
    {
        OrgAddress = PickLocalized(OrgAddressTranslations);
        OrgWorkHours = PickLocalized(OrgWorkHoursTranslations);
    }

    private static string PickLocalized(
        System.Collections.Generic.IReadOnlyDictionary<string, string> dict)
    {
        var lang = Localization.LocalizationService.LangCode(
            Localization.LocalizationService.Current);
        if (dict.TryGetValue(lang, out var v) && !string.IsNullOrWhiteSpace(v))
            return v;
        foreach (var code in new[] { "kk", "uz", "ru" })
        {
            if (dict.TryGetValue(code, out var alt) && !string.IsNullOrWhiteSpace(alt))
                return alt;
        }
        return "";
    }

    public ObservableCollection<string> TranscriptLog { get; } = new();

    public Control CurrentView => CurrentPage switch
    {
        KioskPage.Home => _home ??= new HomePage(),
        KioskPage.Submit => _submit ??= new SubmitPage(),
        KioskPage.Contacts => _contacts ??= new ContactsPage(),
        KioskPage.Qabul => _qabul ??= new QabulPage(),
        KioskPage.ManualSubmit => _manualSubmit ??= new ManualSubmitPage(),
        KioskPage.Feedback => _manualFeedback ??= new ManualFeedbackPage(),
        // Don't cache the AI page — its Loaded/Unloaded handlers manage the
        // voice runtime lifecycle, and a cached instance would skip Loaded
        // on re-entry, leaving the runtime in whatever state Unloaded left
        // it. A fresh instance per visit also resets the silence timer.
        KioskPage.Ai => new AiPage(),
        _ => _home ??= new HomePage(),
    };

    public void Navigate(KioskPage page)
    {
        // Silent navigation: page changes do NOT poke the agent. The agent
        // only speaks in response to actual voice input (or the one-shot
        // [START] the backend sends at WS open). Earlier we sent a
        // synthetic per-page user turn here, which double-fired the
        // greeting after every qabul reset.
        CurrentPage = page;
    }

    /// <summary>Resets the kiosk to home + clears any in-progress submission.</summary>
    public void ResetIdle()
    {
        SubmitStep = SubmitStep.Idle;
        ManualSubmitStep = ManualSubmitStep.Idle;
        SubmitTopic = SubmitBody = SubmitPhone = "";
        SubmittedId = "";
        ShowSubmitSuccess = false;

        AppointmentStep = AppointmentStep.Idle;
        AppointmentTopic = "";
        AppointmentPhoneMasked = "";
        AppointmentVerificationUrl = "";
        AppointmentId = "";
        AppointmentReferenceNo = "";
        AppointmentQrPng = null;
        AppointmentReceiptPdf = null;
        ShowAppointmentSuccess = false;

        ManualFeedbackStep = ManualFeedbackStep.Idle;
        FeedbackType = "";
        FeedbackText = "";
        FeedbackPhone = "";
        FeedbackSubmittedId = "";
        ShowFeedbackSuccess = false;

        LiveTranscript = "";
        Navigate(KioskPage.Home);
    }

    // ── KioskRuntime callbacks (always on UI thread via Dispatcher) ────────

    public void OnConnectionChanged(ConnectionState s)
    {
        ConnectionState = s;
        // Don't show the "reconnecting" overlay if (a) the device is revoked
        // (the red overlay covers that with a clearer action) or (b) the user
        // hasn't started the voice session — disconnected is the EXPECTED state
        // when the kiosk is just sitting idle waiting for someone to tap the orb.
        ShowOfflineOverlay = !IsRevoked && IsVoiceActive && s != ConnectionState.Connected;
    }

    public void OnDeviceRevoked()
    {
        IsRevoked = true;
        ShowOfflineOverlay = false;
    }

    public void OnNavigate(string screen)
    {
        switch (screen)
        {
            case "submit": Navigate(KioskPage.Submit); break;
            case "contacts": Navigate(KioskPage.Contacts); break;
            // Voice agent's old "reception" hop now also means the merged
            // qabul flow — there's no separate reception page anymore.
            case "reception":
            case "qabul": Navigate(KioskPage.Qabul); break;
            case "feedback": Navigate(KioskPage.Feedback); break;
            case "ai": Navigate(KioskPage.Ai); break;
            default: Navigate(KioskPage.Home); break;
        }
    }

    public void OnTranscript(string text, bool final, string speaker)
    {
        // Live overlay shows the latest non-final assistant phrase.
        if (!final) { LiveTranscript = text; return; }
        LiveTranscript = "";
        TranscriptLog.Add($"[{speaker}] {text}");
        // Cap log to last 50 lines so memory doesn't grow forever during long sessions.
        while (TranscriptLog.Count > 50) TranscriptLog.RemoveAt(0);
    }

    public void OnPreview(ApplicationPreviewMessage p)
    {
        SubmitTopic = p.Topic;
        SubmitBody = p.Body;
        SubmitPhone = p.Phone;
        SubmitStep = SubmitStep.Review;
        Navigate(KioskPage.Submit);
    }

    public void OnSubmitted(ApplicationSubmittedMessage s)
    {
        SubmittedId = s.Id;
        SubmitStep = SubmitStep.Done;
        ShowSubmitSuccess = true;
        // Auto-return to home after 4 s so the screen resets for the next visitor.
        DispatcherTimer.RunOnce(() => { ShowSubmitSuccess = false; ResetIdle(); }, TimeSpan.FromSeconds(4));
    }

    public void OnAppointmentProgress(AppointmentProgressMessage p)
    {
        // Stepper-only: advance the highlight + populate just the field that
        // was captured by THIS user reply. Nothing is committed yet; the AI
        // will call preview_appointment with topic + phone once both are in.
        // The Council flow has only two stages — no official.
        switch (p.Stage)
        {
            case "topic":
                if (!string.IsNullOrEmpty(p.Topic)) AppointmentTopic = p.Topic;
                if (AppointmentStep < AppointmentStep.Topic) AppointmentStep = AppointmentStep.Topic;
                Navigate(KioskPage.Qabul);
                break;
            case "phone":
                if (!string.IsNullOrEmpty(p.PhoneMasked)) AppointmentPhoneMasked = p.PhoneMasked;
                if (AppointmentStep < AppointmentStep.Phone) AppointmentStep = AppointmentStep.Phone;
                Navigate(KioskPage.Qabul);
                break;
        }
    }

    public void OnAppointmentPreview(AppointmentPreviewMessage p)
    {
        AppointmentPhoneMasked = p.PhoneMasked;
        AppointmentTopic = p.Topic;
        AppointmentStep = AppointmentStep.Preview;
        Navigate(KioskPage.Qabul);
    }

    public void OnAppointmentSubmitted(AppointmentSubmittedMessage s)
    {
        AppointmentId = s.AppointmentId;
        AppointmentReferenceNo = s.ReferenceNo;
        AppointmentPhoneMasked = s.PhoneMasked;
        AppointmentTopic = s.Topic;
        AppointmentVerificationUrl = s.VerificationUrl;
        // Decode QR + receipt PDF bytes. We log decode failures explicitly
        // because a silent catch here used to mask a real production bug
        // (the visitor sees a blank talon — no QR, no receipt — and there's
        // no way to tell whether the backend sent bad base64 or the kiosk
        // botched the parse). Now any decode error lands in stderr with
        // both the exception message and the input length so we can root-
        // cause it without guessing.
        try
        {
            AppointmentQrPng = Convert.FromBase64String(s.QrPngBase64 ?? "");
        }
        catch (Exception ex)
        {
            AppointmentQrPng = null;
            Console.Error.WriteLine(
                $"[appointment] QR base64 decode failed: {ex.GetType().Name}: {ex.Message} (input_len={(s.QrPngBase64 ?? "").Length})");
        }
        try
        {
            AppointmentReceiptPdf = Convert.FromBase64String(s.ReceiptPdfBase64 ?? "");
        }
        catch (Exception ex)
        {
            AppointmentReceiptPdf = null;
            Console.Error.WriteLine(
                $"[appointment] Receipt PDF base64 decode failed: {ex.GetType().Name}: {ex.Message} (input_len={(s.ReceiptPdfBase64 ?? "").Length})");
        }
        // Voice flow's submit envelope can carry a fresh translations
        // bundle — useful when the super admin renamed the org between
        // the kiosk's last heartbeat and this submit. Empty dict on older
        // backends is fine; UpdateOrgBranding falls through to OrgName.
        if (s.OrgNameTranslations is not null && s.OrgNameTranslations.Count > 0)
        {
            UpdateOrgBranding(s.OrgNameTranslations,
                string.IsNullOrEmpty(OrgName) ? "" : OrgName);
        }
        AppointmentStep = AppointmentStep.Done;
        ShowAppointmentSuccess = true;
        Navigate(KioskPage.Qabul);

        // Auto-print the receipt if the settings allow it. Fire-and-forget —
        // a printer failure must not block the UI from showing the reference
        // number; the visitor can still read the on-screen QR.
        if (AppointmentReceiptPdf is not null && KioskSettings.Current.AutoPrintReceipts)
        {
            var pdf = AppointmentReceiptPdf;
            var printerName = KioskSettings.Current.PrinterName;
            _ = Task.Run(() => ReceiptPrinter.PrintAsync(pdf, printerName));
        }

        // Auto-return to home after 12s — visitor needs time to read the
        // reference number / scan the QR before the screen resets.
        DispatcherTimer.RunOnce(() => { ShowAppointmentSuccess = false; ResetIdle(); }, TimeSpan.FromSeconds(12));
    }

    public void OnFeedbackPreview(FeedbackPreviewMessage p)
    {
        // Voice agent called preview_feedback — mirror the murajaat
        // OnPreview pattern: stash the captured fields and bring the
        // feedback page up to its review step.
        FeedbackType = p.FeedbackType;
        FeedbackText = p.Text;
        FeedbackPhone = p.Phone;
        ManualFeedbackStep = ManualFeedbackStep.Preview;
        Navigate(KioskPage.Feedback);
    }

    public void OnFeedbackSubmitted(FeedbackSubmittedMessage s)
    {
        FeedbackSubmittedId = s.Id;
        if (!string.IsNullOrEmpty(s.FeedbackType)) FeedbackType = s.FeedbackType;
        if (!string.IsNullOrEmpty(s.Text)) FeedbackText = s.Text;
        if (!string.IsNullOrEmpty(s.Phone)) FeedbackPhone = s.Phone;
        ManualFeedbackStep = ManualFeedbackStep.Done;
        ShowFeedbackSuccess = true;
        Navigate(KioskPage.Feedback);
        // Auto-return to home after 4 s so the screen resets for the next visitor.
        DispatcherTimer.RunOnce(() => { ShowFeedbackSuccess = false; ResetIdle(); }, TimeSpan.FromSeconds(4));
    }

    public void OnAudioDone()
    {
        // Could be used to fade the talking robot pose; not wired in slice 8.
    }

    public void OnServerError(string code, string message)
    {
        // Server errors are logged; UI doesn't surface internal codes (per the
        // secrecy rules — operators see them in audit log if needed).
        Console.Error.WriteLine($"[server error] {code} {message}");
    }
}
