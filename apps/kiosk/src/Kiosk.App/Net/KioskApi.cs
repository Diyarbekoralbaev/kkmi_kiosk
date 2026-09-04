using System;
using System.Collections.Generic;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using Kiosk.App.Identity;

namespace Kiosk.App.Net;

// ── Appeal (murojat) — stored in the institute's own database ──
//
// The council build forwarded appeals to an external government cabinet that
// owned a citizen registry, so the payload carried district, quarter, birth
// date and gender. The institute keeps its own appeals and none of those mean
// anything for a student writing to their dean: name, phone, text.
public sealed record AppealRequest
{
    [JsonPropertyName("full_name")] public string FullName { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
    [JsonPropertyName("text")] public string Text { get; init; } = "";
    /// <summary>Optional short subject for the staff list view. The touch form
    /// leaves it null and the backend derives one from the text; the voice flow
    /// has the agent write it.</summary>
    [JsonPropertyName("topic")] public string? Topic { get; init; }
}

public sealed record AppealResponse
{
    [JsonPropertyName("reference")] public string Reference { get; init; } = "";
    [JsonPropertyName("status")] public string Status { get; init; } = "";
}

public sealed record CrashLogRequest
{
    [JsonPropertyName("text")] public string Text { get; init; } = "";
}

// ── Timetable + programmes (touch drill-down; the voice flow gets the same
//    data through WS tool calls, off the same HEMIS mirror) ──

public sealed record FacultyDto
{
    [JsonPropertyName("id")] public int Id { get; init; }
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("code")] public string Code { get; init; } = "";
}

public sealed record FacultyListResponse
{
    [JsonPropertyName("items")] public List<FacultyDto> Items { get; init; } = new();
}

public sealed record GroupListResponse
{
    [JsonPropertyName("items")] public List<GroupDto> Items { get; init; } = new();
}

public sealed record LessonListResponse
{
    [JsonPropertyName("group")] public GroupDto? Group { get; init; }
    [JsonPropertyName("scope")] public string Scope { get; init; } = "";
    [JsonPropertyName("lessons")] public List<LessonDto> Lessons { get; init; } = new();
    [JsonPropertyName("empty_reason")] public string EmptyReason { get; init; } = "";
}

public sealed record DirectionListResponse
{
    [JsonPropertyName("items")] public List<DirectionDto> Items { get; init; } = new();
}

public sealed record DirectionResponse
{
    [JsonPropertyName("item")] public DirectionDto? Item { get; init; }
}

public sealed record CourseListResponse
{
    [JsonPropertyName("items")] public List<CourseDto> Items { get; init; } = new();
}

public sealed record WeekResponse
{
    [JsonPropertyName("group")] public GroupDto? Group { get; init; }
    [JsonPropertyName("week_start")] public string WeekStart { get; init; } = "";
    [JsonPropertyName("week_end")] public string WeekEnd { get; init; } = "";
    [JsonPropertyName("days")] public List<WeekDayDto> Days { get; init; } = new();
    [JsonPropertyName("lessons")] public List<LessonDto> Lessons { get; init; } = new();
}

public sealed record BookListResponse
{
    [JsonPropertyName("items")] public List<BookDto> Items { get; init; } = new();
}

public sealed record BookSectionListResponse
{
    [JsonPropertyName("items")] public List<BookSectionDto> Items { get; init; } = new();
}

// ── Reception booking (touch twin of the voice submit_reception tool) ──

public sealed record ReceptionRequest
{
    [JsonPropertyName("official_id")] public string OfficialId { get; init; } = "";
    [JsonPropertyName("full_name")] public string FullName { get; init; } = "";
    [JsonPropertyName("phone")] public string Phone { get; init; } = "";
    [JsonPropertyName("reason")] public string Reason { get; init; } = "";
}

public sealed record ReceptionResponse
{
    [JsonPropertyName("reference")] public string Reference { get; init; } = "";
    [JsonPropertyName("verify_url")] public string VerifyUrl { get; init; } = "";
    [JsonPropertyName("reception_day")] public string ReceptionDay { get; init; } = "";
    [JsonPropertyName("reception_time")] public string ReceptionTime { get; init; } = "";
}

/// <summary>
/// HTTP client for the kiosk's touch flows. Each request is signed with the
/// device's TPM-bound key via <see cref="SignedHttpClient"/>.
/// </summary>
public static class KioskApi
{
    /// <summary>POST /api/kiosk/appeal — file an appeal from the touch form.
    /// Returns null on failure; the backend logs the real error.</summary>
    public static async Task<AppealResponse?> SubmitAppealAsync(AppealRequest req)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var resp = await SignedHttpClient.PostJsonAsync(
                creds.BackendUrl, "/api/kiosk/appeal",
                req, KioskJsonContext.Default.AppealRequest);
            if (!resp.IsSuccessStatusCode)
            {
                Console.Error.WriteLine($"[api] SubmitAppealAsync HTTP {(int)resp.StatusCode}");
                return null;
            }
            return await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.AppealResponse);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] SubmitAppealAsync: {ex.Message}");
            return null;
        }
    }

    /// <summary>Shared GET helper. Every read here is optional decoration for a
    /// touch screen, so a failure returns null and the page shows its empty
    /// state rather than an error the visitor can do nothing about.</summary>
    private static async Task<T?> GetAsync<T>(
        string path, System.Text.Json.Serialization.Metadata.JsonTypeInfo<T> typeInfo)
        where T : class
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var resp = await SignedHttpClient.GetAsync(creds.BackendUrl, path);
            if (!resp.IsSuccessStatusCode)
            {
                Console.Error.WriteLine($"[api] GET {path} HTTP {(int)resp.StatusCode}");
                return null;
            }
            return await resp.Content.ReadFromJsonAsync(typeInfo);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] GET {path}: {ex.Message}");
            return null;
        }
    }

    public static Task<FacultyListResponse?> GetFacultiesAsync() =>
        GetAsync("/api/kiosk/schedule/faculties", KioskJsonContext.Default.FacultyListResponse);

    public static Task<CourseListResponse?> GetCoursesAsync() =>
        GetAsync("/api/kiosk/schedule/courses",
                 KioskJsonContext.Default.CourseListResponse);

    /// <summary>Groups filtered by faculty, by bachelor course, or unfiltered.</summary>
    public static Task<GroupListResponse?> GetGroupsAsync(
        int? facultyId = null, int? course = null)
    {
        var url = "/api/kiosk/schedule/groups";
        var sep = "?";
        if (facultyId is { } f) { url += $"{sep}faculty_id={f}"; sep = "&"; }
        if (course is { } c) { url += $"{sep}course={c}"; }
        return GetAsync(url, KioskJsonContext.Default.GroupListResponse);
    }

    /// <summary>A group's whole week — per-day counts and every lesson in one
    /// call, so switching day is instant instead of a network wait. Omit
    /// <paramref name="onDate"/> and the backend picks the last taught week.</summary>
    public static Task<WeekResponse?> GetWeekAsync(int groupId, DateTime? onDate = null)
    {
        var url = $"/api/kiosk/schedule/week?group_id={groupId}";
        if (onDate is { } d) url += $"&date={d:yyyy-MM-dd}";
        return GetAsync(url, KioskJsonContext.Default.WeekResponse);
    }

    /// <summary><paramref name="scope"/>: today | tomorrow | week |
    /// last_taught_week | date | week_of. The last two need
    /// <paramref name="onDate"/>; the backend falls back to today without it.</summary>
    public static Task<LessonListResponse?> GetLessonsAsync(
        int groupId, string scope, DateTime? onDate = null)
    {
        var url = $"/api/kiosk/schedule/lessons?group_id={groupId}"
                  + $"&scope={Uri.EscapeDataString(scope)}";
        if (onDate is { } d) url += $"&date={d:yyyy-MM-dd}";
        return GetAsync(url, KioskJsonContext.Default.LessonListResponse);
    }

    public static Task<DirectionListResponse?> GetDirectionsAsync() =>
        GetAsync("/api/kiosk/schedule/directions", KioskJsonContext.Default.DirectionListResponse);

    /// <summary>One programme with the subjects it is taught through.</summary>
    public static Task<DirectionResponse?> GetDirectionAsync(int specialtyId) =>
        GetAsync($"/api/kiosk/schedule/directions/{specialtyId}",
                 KioskJsonContext.Default.DirectionResponse);

    // ── Kutubxona ────────────────────────────────────────────────────────────
    //
    // `locale` is sent so the backend can localize section labels; everything
    // else on a catalogue card is the book's own language and is not
    // translated.

    /// <summary>The stored jacket bytes, or null when the book has none — the
    /// kiosk draws its own cover in that case, so a 404 is an ordinary outcome
    /// rather than a failure worth surfacing.</summary>
    public static async Task<byte[]?> GetBookCoverAsync(string bookId)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var resp = await SignedHttpClient.GetAsync(
                creds.BackendUrl, $"/api/kiosk/library/books/{bookId}/cover.jpg");
            if (!resp.IsSuccessStatusCode) return null;
            return await resp.Content.ReadAsByteArrayAsync();
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] cover {bookId}: {ex.Message}");
            return null;
        }
    }

    /// <summary>One page of a scanned book, already rendered to JPEG by the
    /// backend. The kiosk asks for pictures rather than the PDF: it has no PDF
    /// engine, deliberately — see the note on the endpoint.</summary>
    public static async Task<byte[]?> GetBookPageAsync(string bookId, int page)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var resp = await SignedHttpClient.GetAsync(
                creds.BackendUrl,
                $"/api/kiosk/library/books/{bookId}/page/{page}.jpg");
            if (!resp.IsSuccessStatusCode) return null;
            return await resp.Content.ReadAsByteArrayAsync();
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] page {bookId}/{page}: {ex.Message}");
            return null;
        }
    }

    public static Task<BookSectionListResponse?> GetBookSectionsAsync(string locale) =>
        GetAsync($"/api/kiosk/library/sections?locale={Uri.EscapeDataString(locale)}",
                 KioskJsonContext.Default.BookSectionListResponse);

    public static Task<BookListResponse?> GetBooksAsync(
        string locale, string? section = null, string? query = null)
    {
        var url = $"/api/kiosk/library/books?locale={Uri.EscapeDataString(locale)}";
        if (!string.IsNullOrWhiteSpace(section))
            url += $"&section={Uri.EscapeDataString(section)}";
        if (!string.IsNullOrWhiteSpace(query))
            url += $"&q={Uri.EscapeDataString(query)}";
        return GetAsync(url, KioskJsonContext.Default.BookListResponse);
    }

    /// <summary>GET /api/kiosk/officials — the leadership list. Returns a bare
    /// JSON array (not an {items} envelope) — that endpoint predates the
    /// wrapped convention used by the schedule reads.</summary>
    public static Task<List<OfficialDto>?> GetOfficialsAsync() =>
        GetAsync("/api/kiosk/officials", KioskJsonContext.Default.ListOfficialDto);

    /// <summary>POST /api/kiosk/reception — book a reception from the touch
    /// form. Returns null on failure; the backend logs the real error.</summary>
    public static async Task<ReceptionResponse?> SubmitReceptionAsync(ReceptionRequest req)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null) return null;
        try
        {
            var resp = await SignedHttpClient.PostJsonAsync(
                creds.BackendUrl, "/api/kiosk/reception",
                req, KioskJsonContext.Default.ReceptionRequest);
            if (!resp.IsSuccessStatusCode)
            {
                Console.Error.WriteLine($"[api] SubmitReceptionAsync HTTP {(int)resp.StatusCode}");
                return null;
            }
            return await resp.Content.ReadFromJsonAsync(KioskJsonContext.Default.ReceptionResponse);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] SubmitReceptionAsync: {ex.Message}");
            return null;
        }
    }

    /// <summary>POST /api/kiosk/crashlog — upload the local crash.log after a
    /// crash + watchdog restart so the exact exception is visible remotely.
    /// Fire-and-forget; never throws.</summary>
    public static async Task UploadCrashLogAsync(string text)
    {
        var creds = DeviceKeyStore.Load();
        if (creds is null || string.IsNullOrWhiteSpace(text)) return;
        try
        {
            await SignedHttpClient.PostJsonAsync(
                creds.BackendUrl, "/api/kiosk/crashlog",
                new CrashLogRequest { Text = text }, KioskJsonContext.Default.CrashLogRequest);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[api] UploadCrashLogAsync: {ex.Message}");
        }
    }
}
