using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using Kiosk.App.Net;
using Kiosk.App.Pages;

namespace Kiosk.App.State;

public enum KioskPage
{
    Home,
    /// <summary>AI voice murajat preview/result page. The agent drives it
    /// over the WS (MurajatPreview → Review, MurajatSubmitted → Done).</summary>
    Submit,
    Contacts,
    Ai,
    /// <summary>Manual touch-driven murajat flow (NEW). Reached by tapping the
    /// Home Murajat tile. Phone → (lookup) → confirm/full-form → text →
    /// preview → submit. Distinct from the AI voice flow above.</summary>
    ManualSubmit,
}

/// <summary>Step machine shared by the AI voice preview page (Review/Done
/// only) and the manual touch murajat flow (the full machine). One enum so
/// the two paths read the same SubmitStep; only one page is ever visible at
/// a time and each resets the state on entry.</summary>
public enum SubmitStep
{
    Idle,
    Phone,
    Confirm,
    Form,
    Text,
    Review,
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
    private ManualSubmitPage? _manualSubmit;

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

    // ── Murajat (appeal) state — shared by the AI voice preview page and the
    // manual touch flow. A murajat is a single free-text body + phone, plus
    // optional personal fields collected for a new / «men emas» citizen. ───────
    [ObservableProperty] private SubmitStep _submitStep = SubmitStep.Idle;
    [ObservableProperty] private string _submitText = "";
    [ObservableProperty] private string _submitPhone = "";
    /// <summary>true = an existing citizen confirmed identity (phone + text
    /// only). false = a new / «men emas» citizen (personal fields are sent).</summary>
    [ObservableProperty] private bool _submitConfirmed;
    [ObservableProperty] private string _submitFirstName = "";
    [ObservableProperty] private string _submitLastName = "";
    /// <summary>The cabinet's appeal number, e.g. "25678/26". Shown on the
    /// success talon.</summary>
    [ObservableProperty] private string _appealNumber = "";
    [ObservableProperty] private bool _showSubmitSuccess;

    // ── Manual-form-only collected fields (new / «men emas» citizen) ───────────
    [ObservableProperty] private string _submitBirthDate = "";
    /// <summary>1 = male, 0 = female; null = not chosen yet.</summary>
    [ObservableProperty] private int? _submitGender;
    [ObservableProperty] private int? _submitDistrictId;
    [ObservableProperty] private int? _submitQuarterId;
    [ObservableProperty] private string _submitAddress = "";

    /// <summary>Result of the phone lookup that opened the manual flow.</summary>
    public bool LookupExists { get; set; }
    public PersonalDto? LookupPersonal { get; set; }

    // ── Locations reference cache (in-memory only, never persisted) ────────────
    public List<DistrictDto> Districts { get; private set; } = new();
    public List<QuarterDto> Quarters { get; private set; } = new();
    public bool LocationsLoaded { get; private set; }

    /// <summary>Stash the districts + quarters reference for the manual form.
    /// Loaded once when the manual page opens; cleared on session reset.</summary>
    public void SetLocations(LocationsResponse resp)
    {
        Districts = resp.Districts ?? new();
        Quarters = resp.Quarters ?? new();
        LocationsLoaded = true;
    }

    private void ClearLocations()
    {
        Districts = new();
        Quarters = new();
        LocationsLoaded = false;
    }

    /// <summary>Quarters that belong to the selected district id.</summary>
    public List<QuarterDto> QuartersForDistrict(int districtId) =>
        Quarters.Where(q => q.DistrictId == districtId).ToList();

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
        KioskPage.ManualSubmit => _manualSubmit ??= new ManualSubmitPage(),
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
        // [START] the backend sends at WS open).
        CurrentPage = page;
    }

    /// <summary>Resets the kiosk to home + clears any in-progress murajat.</summary>
    public void ResetIdle()
    {
        SubmitStep = SubmitStep.Idle;
        SubmitText = "";
        SubmitPhone = "";
        SubmitConfirmed = false;
        SubmitFirstName = "";
        SubmitLastName = "";
        AppealNumber = "";
        ShowSubmitSuccess = false;

        SubmitBirthDate = "";
        SubmitGender = null;
        SubmitDistrictId = null;
        SubmitQuarterId = null;
        SubmitAddress = "";
        LookupExists = false;
        LookupPersonal = null;
        ClearLocations();

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

    /// <summary>AI agent composed a murajat draft (preview_murajat tool). Stash
    /// the single text + phone (+ name when the citizen is new) and bring the
    /// voice preview page up to its Review step.</summary>
    public void OnMurajatPreview(MurajatPreviewMessage p)
    {
        SubmitText = p.Text;
        SubmitPhone = p.Phone;
        SubmitConfirmed = p.Confirmed;
        SubmitFirstName = p.FirstName;
        SubmitLastName = p.LastName;
        SubmitStep = SubmitStep.Review;
        Navigate(KioskPage.Submit);
    }

    /// <summary>AI agent submitted the murajat (submit_murajat tool). Show the
    /// success talon with the cabinet's appeal number, then auto-return home.</summary>
    public void OnMurajatSubmitted(MurajatSubmittedMessage s)
    {
        AppealNumber = s.AppealNumber;
        if (!string.IsNullOrEmpty(s.PhoneMasked)) SubmitPhone = s.PhoneMasked;
        // The submit envelope can carry a fresh translations bundle — useful
        // when the super admin renamed the org since the last heartbeat.
        if (s.OrgNameTranslations is not null && s.OrgNameTranslations.Count > 0)
        {
            UpdateOrgBranding(s.OrgNameTranslations,
                string.IsNullOrEmpty(OrgName) ? "" : OrgName);
        }
        SubmitStep = SubmitStep.Done;
        ShowSubmitSuccess = true;
        // Auto-return to home after 6 s so the screen resets for the next visitor.
        DispatcherTimer.RunOnce(() => { ShowSubmitSuccess = false; ResetIdle(); }, TimeSpan.FromSeconds(6));
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
