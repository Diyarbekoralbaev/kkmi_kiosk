using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using Avalonia.Controls;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using Kiosk.App.Net;
using Kiosk.App.Pages;

namespace Kiosk.App.State;

/// <summary>The six home tiles plus the shared chrome screens.
///
/// Each tile maps to a backend "menu" (see <see cref="MenuFor"/>) that decides
/// which prompt focus block and which tools the agent gets for that session.
/// </summary>
public enum KioskPage
{
    Home,
    /// <summary>AI Maslahatchi — general Q&amp;A with the 3D robot.</summary>
    Ai,
    /// <summary>AI Library — "coming soon" until the catalogue is connected.</summary>
    Library,
    /// <summary>AI Abituriyent — degree programmes for applicants.</summary>
    Abituriyent,
    /// <summary>AI Murojat — file an appeal to the institute.</summary>
    Murojat,
    /// <summary>Dars jadvali — group timetables from the HEMIS mirror.</summary>
    Jadval,
    /// <summary>Rahbariyat qabuli — book a reception with the leadership.</summary>
    Qabul,
    Contacts,
}

/// <summary>Step machine shared by the touch forms (murojat, reception). Only
/// one form is ever on screen and each resets on entry.</summary>
public enum SubmitStep
{
    Idle,
    Phone,
    Name,
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
    private LibraryPage? _library;
    private AbituriyentPage? _abituriyent;
    private MurojatPage? _murojat;
    private SchedulePage? _jadval;
    private ReceptionPage? _qabul;
    private ContactsPage? _contacts;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CurrentView))]
    private KioskPage _currentPage = KioskPage.Home;

    [ObservableProperty] private ConnectionState _connectionState = ConnectionState.Disconnected;
    [ObservableProperty] private bool _showOfflineOverlay;

    /// <summary>True when the backend rejected this device's key (revoked or
    /// unknown). Flips to the "needs re-enrolment" overlay rather than the
    /// transient offline one — very different operator actions.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowOfflineOverlay))]
    private bool _isRevoked;

    /// <summary>Whether the visitor has STARTED a voice session. The offline
    /// overlay is suppressed while voice is intentionally off — disconnected is
    /// the EXPECTED state for an idle kiosk waiting for someone to walk up.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowOfflineOverlay))]
    private bool _isVoiceActive;

    /// <summary>RMS of the last captured frame, normalised to [0,1]. Drives the MicOrb pulse.</summary>
    [ObservableProperty] private float _inputLevel;
    /// <summary>True while the local VAD says the visitor is speaking.</summary>
    [ObservableProperty] private bool _isSpeaking;

    [ObservableProperty] private string _liveTranscript = "";

    /// <summary>Backend menu name for a page. Pages with no agent (Home,
    /// Contacts) never open a session, so they map to the general assistant
    /// purely as a safe default.</summary>
    public static string MenuFor(KioskPage page) => page switch
    {
        KioskPage.Library => "library",
        KioskPage.Abituriyent => "abituriyent",
        KioskPage.Murojat => "murojat",
        KioskPage.Jadval => "jadval",
        KioskPage.Qabul => "qabul",
        _ => "maslahatchi",
    };

    // ── Murojat (appeal) ──────────────────────────────────────────────────────
    [ObservableProperty] private SubmitStep _submitStep = SubmitStep.Idle;
    [ObservableProperty] private string _submitName = "";
    [ObservableProperty] private string _submitPhone = "";
    [ObservableProperty] private string _submitTopic = "";
    [ObservableProperty] private string _submitText = "";
    /// <summary>Reference shown on the success talon, e.g. "M-1A2B3C4D".</summary>
    [ObservableProperty] private string _submitReference = "";
    [ObservableProperty] private bool _showSubmitSuccess;

    // ── Reception (qabul) ─────────────────────────────────────────────────────
    [ObservableProperty] private string _receptionOfficialId = "";
    [ObservableProperty] private string _receptionOfficialName = "";
    [ObservableProperty] private string _receptionOfficialPosition = "";
    [ObservableProperty] private string _receptionDay = "";
    [ObservableProperty] private string _receptionTime = "";
    [ObservableProperty] private string _receptionReason = "";
    [ObservableProperty] private string _receptionReference = "";
    public ObservableCollection<OfficialDto> Leadership { get; } = new();

    // ── Timetable ─────────────────────────────────────────────────────────────
    [ObservableProperty] private string _scheduleGroupName = "";
    [ObservableProperty] private string _scheduleScope = "";
    /// <summary>"" | "no_lessons_that_day" | "year_not_published". The last one
    /// is normal over the summer break and must not read as a broken kiosk.</summary>
    [ObservableProperty] private string _scheduleEmptyReason = "";
    public ObservableCollection<LessonDto> Lessons { get; } = new();
    public ObservableCollection<GroupDto> GroupChoices { get; } = new();

    // ── Abituriyent ───────────────────────────────────────────────────────────
    public ObservableCollection<DirectionDto> Directions { get; } = new();
    [ObservableProperty] private DirectionDto? _selectedDirection;

    // ── Info card (shared visual aid the agent pushes while talking) ──────────
    [ObservableProperty] private string _infoCardTitle = "";
    [ObservableProperty] private bool _showInfoCard;
    public ObservableCollection<string> InfoCardBullets { get; } = new();

    // ── Org branding ──────────────────────────────────────────────────────────

    /// <summary>Institute name in the header / talon. Hydrated from the last
    /// persisted heartbeat at startup, then refreshed on every heartbeat so a
    /// panel rename propagates without re-enrolment. Language-aware — see
    /// <see cref="UpdateOrgBranding"/>.</summary>
    [ObservableProperty] private string _orgName = "";

    /// <summary>{"uz","kk","ru","en"}. The setter does NOT recompute
    /// <see cref="OrgName"/> on its own; callers always pair it with
    /// <see cref="UpdateOrgBranding"/> so the dict and the resolved name land
    /// atomically.</summary>
    [ObservableProperty] private Dictionary<string, string> _orgNameTranslations = new();

    /// <summary>Legacy single-string name, kept as the last-ditch fallback when
    /// the translations dict is empty or missing the active locale.</summary>
    private string _orgNameFallback = "";

    public void UpdateOrgBranding(
        IReadOnlyDictionary<string, string>? translations, string fallback)
    {
        var dict = new Dictionary<string, string>();
        if (translations is not null)
        {
            foreach (var kvp in translations)
            {
                if (!string.IsNullOrWhiteSpace(kvp.Value)) dict[kvp.Key] = kvp.Value;
            }
        }
        _orgNameFallback = fallback ?? "";
        OrgNameTranslations = dict;
        OrgName = PickLocalized(dict, _orgNameFallback);
    }

    private static string PickLocalized(
        IReadOnlyDictionary<string, string> dict, string fallback = "")
    {
        var lang = Localization.LocalizationService.LangCode(
            Localization.LocalizationService.Current);
        if (dict.TryGetValue(lang, out var v) && !string.IsNullOrWhiteSpace(v)) return v;
        foreach (var code in new[] { "uz", "kk", "ru", "en" })
        {
            if (dict.TryGetValue(code, out var alt) && !string.IsNullOrWhiteSpace(alt))
                return alt;
        }
        return fallback ?? "";
    }

    private void OnLocalizationLanguageChanged(Localization.Language _)
    {
        OrgName = PickLocalized(OrgNameTranslations ?? new(), _orgNameFallback);
        RefreshLocalizedContacts();
    }

    private SessionStore()
    {
        // Subscribed once for the process lifetime — SessionStore is a
        // process-wide singleton, so there is nothing to unsubscribe from.
        Localization.LocalizationService.LanguageChanged += OnLocalizationLanguageChanged;
    }

    /// <summary>Localized weather text, e.g. "Nukus · +25°". Empty hides the row.</summary>
    [ObservableProperty] private string _weatherText = "";

    /// <summary>Help-desk phone in the footer band. Empty hides the row.</summary>
    [ObservableProperty] private string _helplinePhone = "";

    [ObservableProperty] private Dictionary<string, string> _orgAddressTranslations = new();
    [ObservableProperty] private Dictionary<string, string> _orgWorkHoursTranslations = new();
    [ObservableProperty] private string _orgEmail = "";
    [ObservableProperty] private string _orgAddress = "";
    [ObservableProperty] private string _orgWorkHours = "";

    /// <summary>Update the Contacts page bundle in one call. Empty values stay
    /// empty strings so the rows keep their alignment rather than collapsing.</summary>
    public void UpdateContactInfo(
        IReadOnlyDictionary<string, string>? address,
        string email,
        IReadOnlyDictionary<string, string>? workHours,
        string helplinePhone)
    {
        OrgAddressTranslations = CopyDict(address);
        OrgWorkHoursTranslations = CopyDict(workHours);
        OrgEmail = email ?? "";
        HelplinePhone = helplinePhone ?? "";
        RefreshLocalizedContacts();
    }

    private static Dictionary<string, string> CopyDict(
        IReadOnlyDictionary<string, string>? src)
    {
        var dst = new Dictionary<string, string>();
        if (src is null) return dst;
        foreach (var kvp in src) dst[kvp.Key] = kvp.Value ?? "";
        return dst;
    }

    private void RefreshLocalizedContacts()
    {
        OrgAddress = PickLocalized(OrgAddressTranslations);
        OrgWorkHours = PickLocalized(OrgWorkHoursTranslations);
    }

    public ObservableCollection<string> TranscriptLog { get; } = new();

    public Control CurrentView => CurrentPage switch
    {
        KioskPage.Home => _home ??= new HomePage(),
        KioskPage.Library => _library ??= new LibraryPage(),
        KioskPage.Abituriyent => _abituriyent ??= new AbituriyentPage(),
        KioskPage.Murojat => _murojat ??= new MurojatPage(),
        KioskPage.Jadval => _jadval ??= new SchedulePage(),
        KioskPage.Qabul => _qabul ??= new ReceptionPage(),
        KioskPage.Contacts => _contacts ??= new ContactsPage(),
        // Never cached: AiPage's Loaded/Unloaded manage the voice runtime, and a
        // cached instance would skip Loaded on re-entry, leaving the runtime in
        // whatever state Unloaded left it. A fresh instance also resets the
        // silence timer.
        KioskPage.Ai => new AiPage(),
        _ => _home ??= new HomePage(),
    };

    public void Navigate(KioskPage page)
    {
        // Silent: a page change never pokes the agent. The agent speaks only in
        // response to voice input, or the one-shot [START] at WS open.
        CurrentPage = page;
    }

    /// <summary>Reset to home and clear every in-progress flow.</summary>
    public void ResetIdle()
    {
        SubmitStep = SubmitStep.Idle;
        SubmitName = "";
        SubmitPhone = "";
        SubmitTopic = "";
        SubmitText = "";
        SubmitReference = "";
        ShowSubmitSuccess = false;

        ReceptionOfficialId = "";
        ReceptionOfficialName = "";
        ReceptionOfficialPosition = "";
        ReceptionDay = "";
        ReceptionTime = "";
        ReceptionReason = "";
        ReceptionReference = "";
        Leadership.Clear();

        ScheduleGroupName = "";
        ScheduleScope = "";
        ScheduleEmptyReason = "";
        Lessons.Clear();
        GroupChoices.Clear();

        Directions.Clear();
        SelectedDirection = null;

        ShowInfoCard = false;
        InfoCardTitle = "";
        InfoCardBullets.Clear();

        LiveTranscript = "";
        Navigate(KioskPage.Home);
    }

    // ── KioskRuntime callbacks (always on the UI thread via Dispatcher) ───────

    public void OnConnectionChanged(ConnectionState s)
    {
        ConnectionState = s;
        // Don't show "reconnecting" when (a) the device is revoked — the red
        // overlay covers that with a clearer action — or (b) voice was never
        // started, which is the normal idle state.
        ShowOfflineOverlay = !IsRevoked && IsVoiceActive && s != ConnectionState.Connected;
    }

    public void OnDeviceRevoked()
    {
        IsRevoked = true;
        ShowOfflineOverlay = false;
    }

    public void OnNavigate(string screen)
    {
        Navigate(screen switch
        {
            "maslahatchi" => KioskPage.Ai,
            "library" => KioskPage.Library,
            "abituriyent" => KioskPage.Abituriyent,
            "murojat" => KioskPage.Murojat,
            "jadval" => KioskPage.Jadval,
            "qabul" => KioskPage.Qabul,
            "contacts" => KioskPage.Contacts,
            _ => KioskPage.Home,
        });
    }

    public void OnTranscript(string text, bool final, string speaker)
    {
        if (!final) { LiveTranscript = text; return; }
        LiveTranscript = "";
        TranscriptLog.Add($"[{speaker}] {text}");
        // Cap so memory doesn't grow through a long session.
        while (TranscriptLog.Count > 50) TranscriptLog.RemoveAt(0);
    }

    // ── Appeal ────────────────────────────────────────────────────────────────

    public void OnMurojatPreview(MurojatPreviewMessage p)
    {
        SubmitName = p.FullName;
        SubmitPhone = p.Phone;
        SubmitTopic = p.Topic;
        SubmitText = p.Text;
        SubmitStep = SubmitStep.Review;
        Navigate(KioskPage.Murojat);
    }

    public void OnMurojatSubmitted(MurojatSubmittedMessage s)
    {
        SubmitReference = s.Reference;
        if (!string.IsNullOrWhiteSpace(s.FullName)) SubmitName = s.FullName;
        SubmitStep = SubmitStep.Done;
        ShowSubmitSuccess = true;
        // Auto-return home so the screen resets for the next visitor.
        DispatcherTimer.RunOnce(
            () => { ShowSubmitSuccess = false; ResetIdle(); }, TimeSpan.FromSeconds(8));
    }

    // ── Timetable ─────────────────────────────────────────────────────────────

    public void OnSchedule(ScheduleMessage m)
    {
        ScheduleGroupName = m.Group?.Name ?? "";
        ScheduleScope = m.Scope;
        ScheduleEmptyReason = m.EmptyReason;
        Lessons.Clear();
        foreach (var l in m.Lessons) Lessons.Add(l);
        GroupChoices.Clear();
        Navigate(KioskPage.Jadval);
    }

    public void OnGroupChoices(GroupChoicesMessage m)
    {
        GroupChoices.Clear();
        foreach (var g in m.Items) GroupChoices.Add(g);
        Navigate(KioskPage.Jadval);
    }

    // ── Abituriyent ───────────────────────────────────────────────────────────

    public void OnDirections(DirectionsMessage m)
    {
        Directions.Clear();
        foreach (var d in m.Items) Directions.Add(d);
        SelectedDirection = null;
        Navigate(KioskPage.Abituriyent);
    }

    public void OnDirection(DirectionMessage m)
    {
        SelectedDirection = m.Item;
        Navigate(KioskPage.Abituriyent);
    }

    // ── Reception ─────────────────────────────────────────────────────────────

    public void OnLeadership(LeadershipMessage m)
    {
        Leadership.Clear();
        foreach (var o in m.Items) Leadership.Add(o);
        Navigate(KioskPage.Qabul);
    }

    public void OnReceptionPreview(ReceptionPreviewMessage m)
    {
        SubmitName = m.FullName;
        SubmitPhone = m.Phone;
        ReceptionReason = m.Reason;
        ApplyOfficial(m.Official);
        SubmitStep = SubmitStep.Review;
        Navigate(KioskPage.Qabul);
    }

    public void OnReceptionSubmitted(ReceptionSubmittedMessage m)
    {
        ReceptionReference = m.Reference;
        ApplyOfficial(m.Official);
        SubmitStep = SubmitStep.Done;
        ShowSubmitSuccess = true;
        DispatcherTimer.RunOnce(
            () => { ShowSubmitSuccess = false; ResetIdle(); }, TimeSpan.FromSeconds(8));
    }

    private void ApplyOfficial(OfficialDto? o)
    {
        if (o is null) return;
        ReceptionOfficialId = o.Id;
        ReceptionOfficialName = o.Name;
        ReceptionOfficialPosition = o.Position;
        ReceptionDay = o.ReceptionDay;
        ReceptionTime = o.ReceptionTime;
    }

    // ── Info card ─────────────────────────────────────────────────────────────

    public void OnInfoCard(InfoCardMessage m)
    {
        InfoCardTitle = m.Title;
        InfoCardBullets.Clear();
        foreach (var b in m.Bullets) InfoCardBullets.Add(b);
        ShowInfoCard = InfoCardBullets.Count > 0;
    }

    public void OnAudioDone()
    {
        // Reserved for a talking-robot pose fade; not wired.
    }

    public void OnServerError(string code, string message)
    {
        // Internal codes are never surfaced to visitors (see the error-secrecy
        // rule); operators read them from the audit log.
        Console.Error.WriteLine($"[server error] {code} {message}");
    }
}
