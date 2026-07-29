using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Kiosk.App.Net;

/// <summary>
/// Wire DTOs that mirror the backend's Pydantic schemas. Property names use
/// snake_case via JsonPropertyName so the .NET source generator can serialize
/// without reflection (AOT-friendly in slice 13).
/// </summary>
public sealed record EnrollRequest
{
    [JsonPropertyName("enrollment_code")] public string EnrollmentCode { get; init; } = "";
    [JsonPropertyName("public_key_pem")] public string PublicKeyPem { get; init; } = "";
    [JsonPropertyName("tpm_attested")] public bool TpmAttested { get; init; }
}

public sealed record EnrollResponse
{
    [JsonPropertyName("device_id")] public string DeviceId { get; init; } = "";
    [JsonPropertyName("org_name")] public string OrgName { get; init; } = "";
    [JsonPropertyName("org_slug")] public string OrgSlug { get; init; } = "";
    /// <summary>{"uz": "...", "kk": "...", "ru": "..."} — localized display
    /// names. Older backends omit this; consumers fall back to OrgName.</summary>
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; init; } = new();
    /// <summary>Localized street address — kiosk Contacts page row 1.</summary>
    [JsonPropertyName("address_translations")]
    public Dictionary<string, string> AddressTranslations { get; init; } = new();
    [JsonPropertyName("email")] public string Email { get; init; } = "";
    /// <summary>Localized working hours line — Contacts page row 4.</summary>
    [JsonPropertyName("work_hours_translations")]
    public Dictionary<string, string> WorkHoursTranslations { get; init; } = new();
    [JsonPropertyName("helpline_phone")] public string HelplinePhone { get; init; } = "";
}

public sealed record AuthChallengeResponse
{
    [JsonPropertyName("nonce")] public string Nonce { get; init; } = "";
    [JsonPropertyName("expires_at")] public string ExpiresAt { get; init; } = "";
}

public sealed record WeatherDto
{
    [JsonPropertyName("city")] public string City { get; init; } = "";
    [JsonPropertyName("temp_c")] public int TempC { get; init; }
    [JsonPropertyName("fetched_at")] public string FetchedAt { get; init; } = "";
}

public sealed record HeartbeatResponse
{
    [JsonPropertyName("ok")] public bool Ok { get; init; }
    [JsonPropertyName("org_name")] public string OrgName { get; init; } = "";
    [JsonPropertyName("org_slug")] public string OrgSlug { get; init; } = "";
    /// <summary>Localized variants. Sent on every heartbeat so super-panel
    /// renames in any language reach the kiosk within one tick.</summary>
    [JsonPropertyName("org_name_translations")]
    public Dictionary<string, string> OrgNameTranslations { get; init; } = new();
    // null when org has no geo configured or every weather fetch failed.
    [JsonPropertyName("weather")] public WeatherDto? Weather { get; init; }
    [JsonPropertyName("helpline_phone")] public string HelplinePhone { get; init; } = "";
    /// <summary>Localized street address — kiosk Contacts page row 1.</summary>
    [JsonPropertyName("address_translations")]
    public Dictionary<string, string> AddressTranslations { get; init; } = new();
    [JsonPropertyName("email")] public string Email { get; init; } = "";
    /// <summary>Localized working hours line — Contacts page row 4.</summary>
    [JsonPropertyName("work_hours_translations")]
    public Dictionary<string, string> WorkHoursTranslations { get; init; } = new();
}

public sealed record ApiError
{
    [JsonPropertyName("code")] public string Code { get; init; } = "";
    [JsonPropertyName("message")] public string Message { get; init; } = "";
    [JsonPropertyName("correlation_id")] public string CorrelationId { get; init; } = "";
}

// ── Inbound WS JSON envelopes (server → client) ─────────────────────────────

public sealed record NavigateMessage
{
    [JsonPropertyName("screen")] public string Screen { get; init; } = "home";
}

public sealed record TranscriptMessage
{
    [JsonPropertyName("text")] public string Text { get; init; } = "";
    [JsonPropertyName("final")] public bool Final { get; init; }
    [JsonPropertyName("speaker")] public string Speaker { get; init; } = "";
}

public sealed record MurojatPreviewMessage
{
    [JsonPropertyName("full_name")] public string FullName { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
    /// <summary>Short subject the agent wrote for the staff list view.</summary>
    [JsonPropertyName("topic")] public string Topic { get; init; } = "";
    /// <summary>The appeal body, in the visitor's own words.</summary>
    [JsonPropertyName("text")] public string Text { get; init; } = "";
}

public sealed record MurojatSubmittedMessage
{
    /// <summary>Human-facing reference, e.g. "M-1A2B3C4D".</summary>
    [JsonPropertyName("reference")] public string Reference { get; init; } = "";
    [JsonPropertyName("full_name")] public string FullName { get; init; } = "";
}

// ── Dars jadvali ─────────────────────────────────────────────────────────────

public sealed record GroupDto
{
    [JsonPropertyName("id")] public int Id { get; init; }
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("specialty")] public string Specialty { get; init; } = "";
    /// <summary>Teaching language: O'zbek | Qoraqalpoq | Rus | Ingliz.</summary>
    [JsonPropertyName("language")] public string Language { get; init; } = "";
}

public sealed record LessonDto
{
    [JsonPropertyName("date")] public string Date { get; init; } = "";
    /// <summary>ISO weekday, 1 = Monday.</summary>
    [JsonPropertyName("weekday")] public int Weekday { get; init; }
    [JsonPropertyName("start")] public string Start { get; init; } = "";
    [JsonPropertyName("end")] public string End { get; init; } = "";
    [JsonPropertyName("subject")] public string Subject { get; init; } = "";
    [JsonPropertyName("teacher")] public string Teacher { get; init; } = "";
    [JsonPropertyName("room")] public string Room { get; init; } = "";
    [JsonPropertyName("building")] public string Building { get; init; } = "";
    /// <summary>Ma'ruza | Amaliy | Laboratoriya | Seminar.</summary>
    [JsonPropertyName("kind")] public string Kind { get; init; } = "";
}

public sealed record ScheduleMessage
{
    [JsonPropertyName("group")] public GroupDto? Group { get; init; }
    [JsonPropertyName("scope")] public string Scope { get; init; } = "";
    [JsonPropertyName("lessons")] public List<LessonDto> Lessons { get; init; } = new();
    /// <summary>Why the list is empty, when it is: "no_lessons_that_day" (a free
    /// day) or "year_not_published" (the new academic year is not in HEMIS yet —
    /// normal over the summer). The two need opposite explanations on screen.</summary>
    [JsonPropertyName("empty_reason")] public string EmptyReason { get; init; } = "";
}

public sealed record GroupChoicesMessage
{
    [JsonPropertyName("query")] public string Query { get; init; } = "";
    [JsonPropertyName("items")] public List<GroupDto> Items { get; init; } = new();
}

// ── Abituriyent ──────────────────────────────────────────────────────────────

public sealed record DirectionDto
{
    [JsonPropertyName("id")] public int Id { get; init; }
    [JsonPropertyName("code")] public string Code { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("faculty")] public string Faculty { get; init; } = "";
    /// <summary>Bakalavr | Magistr | Ordinatura.</summary>
    [JsonPropertyName("education_type")] public string EducationType { get; init; } = "";
    /// <summary>How many active groups study this programme — the only honest
    /// signal of its size the mirror carries.</summary>
    [JsonPropertyName("group_count")] public int GroupCount { get; init; }
    /// <summary>Teaching languages that really have groups, e.g.
    /// ["Ingliz","Qoraqalpoq","Rus","O‘zbek"]. HEMIS records the language on
    /// the group, not the programme, so this is aggregated server-side.</summary>
    [JsonPropertyName("languages")] public List<string> Languages { get; init; } = new();
    /// <summary>Subjects the degree is actually taught through, most-timetabled
    /// first. Only populated by the detail endpoint / show_direction — the list
    /// endpoint leaves it empty.</summary>
    [JsonPropertyName("subjects")] public List<string> Subjects { get; init; } = new();
}

/// <summary>A bachelor course (1-6) and how many groups sit in it. Derived
/// server-side from the group number — HEMIS publishes no course field.</summary>
public sealed record CourseDto
{
    [JsonPropertyName("course")] public int Course { get; init; }
    [JsonPropertyName("group_count")] public int GroupCount { get; init; }
}

/// <summary>One column of the week strip.</summary>
public sealed record WeekDayDto
{
    [JsonPropertyName("date")] public string Date { get; init; } = "";
    /// <summary>ISO weekday, 1 = Monday.</summary>
    [JsonPropertyName("weekday")] public int Weekday { get; init; }
    [JsonPropertyName("count")] public int Count { get; init; }
    [JsonPropertyName("is_today")] public bool IsToday { get; init; }
}

// ── Kutubxona ────────────────────────────────────────────────────────────────

/// <summary>One catalogue card. Unlike everything else the kiosk reads, this
/// comes from a table the institute types into rather than the HEMIS mirror, so
/// blank fields are normal — they mean "not recorded yet", never "unknown to
/// the system".</summary>
public sealed record BookDto
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("title")] public string Title { get; init; } = "";
    [JsonPropertyName("authors")] public string Authors { get; init; } = "";
    [JsonPropertyName("year")] public int? Year { get; init; }
    [JsonPropertyName("publisher")] public string Publisher { get; init; } = "";
    [JsonPropertyName("isbn")] public string Isbn { get; init; } = "";
    [JsonPropertyName("language")] public string Language { get; init; } = "";
    [JsonPropertyName("section")] public string Section { get; init; } = "";
    /// <summary>Already localized by the backend from the `locale` query.</summary>
    [JsonPropertyName("section_label")] public string SectionLabel { get; init; } = "";
    [JsonPropertyName("copies")] public int Copies { get; init; }
    [JsonPropertyName("shelf")] public string Shelf { get; init; } = "";
    [JsonPropertyName("description")] public string Description { get; init; } = "";
    [JsonPropertyName("available")] public bool Available { get; init; } = true;
    /// <summary>A jacket image is stored for this book. When false the kiosk
    /// draws its own designed cover instead of showing a broken frame.</summary>
    [JsonPropertyName("has_cover")] public bool HasCover { get; init; }
}

public sealed record BookSectionDto
{
    [JsonPropertyName("section")] public string Section { get; init; } = "";
    [JsonPropertyName("label")] public string Label { get; init; } = "";
    [JsonPropertyName("count")] public int Count { get; init; }
}

public sealed record BooksMessage
{
    [JsonPropertyName("items")] public List<BookDto> Items { get; init; } = new();
    [JsonPropertyName("query")] public string Query { get; init; } = "";
    [JsonPropertyName("section")] public string Section { get; init; } = "";
}

public sealed record BookSectionsMessage
{
    [JsonPropertyName("items")] public List<BookSectionDto> Items { get; init; } = new();
}

public sealed record DirectionsMessage
{
    [JsonPropertyName("items")] public List<DirectionDto> Items { get; init; } = new();
}

public sealed record DirectionMessage
{
    [JsonPropertyName("item")] public DirectionDto? Item { get; init; }
}

// ── Rahbariyat qabuli ────────────────────────────────────────────────────────

public sealed record OfficialDto
{
    [JsonPropertyName("id")] public string Id { get; init; } = "";
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("position")] public string Position { get; init; } = "";
    /// <summary>ISO short day code ("mon".."sun"); the kiosk localizes it.</summary>
    [JsonPropertyName("reception_day")] public string ReceptionDay { get; init; } = "";
    [JsonPropertyName("reception_time")] public string ReceptionTime { get; init; } = "";
}

public sealed record LeadershipMessage
{
    [JsonPropertyName("items")] public List<OfficialDto> Items { get; init; } = new();
}

public sealed record ReceptionPreviewMessage
{
    [JsonPropertyName("full_name")] public string FullName { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
    [JsonPropertyName("reason")] public string Reason { get; init; } = "";
    [JsonPropertyName("official")] public OfficialDto? Official { get; init; }
}

public sealed record ReceptionSubmittedMessage
{
    /// <summary>Human-facing reference, e.g. "Q-1A2B3C4D".</summary>
    [JsonPropertyName("reference")] public string Reference { get; init; } = "";
    /// <summary>URL encoded into the printed ticket's QR code.</summary>
    [JsonPropertyName("verify_url")] public string VerifyUrl { get; init; } = "";
    [JsonPropertyName("official")] public OfficialDto? Official { get; init; }
}

// ── Shared visual aid ────────────────────────────────────────────────────────

public sealed record InfoCardMessage
{
    [JsonPropertyName("title")] public string Title { get; init; } = "";
    [JsonPropertyName("bullets")] public List<string> Bullets { get; init; } = new();
}

public sealed record ServerErrorMessage
{
    [JsonPropertyName("code")] public string Code { get; init; } = "";
    [JsonPropertyName("message")] public string Message { get; init; } = "";
}

// Outbound JSON envelopes (turn_start / turn_end) are tiny static literals
// sent by KioskClient directly — no record types needed.
