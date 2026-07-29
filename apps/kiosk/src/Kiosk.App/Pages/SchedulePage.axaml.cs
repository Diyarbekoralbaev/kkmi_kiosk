using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>
/// Timetable browser. Four panels, one visible at a time:
///
///   Course → Group → Week      the touch path
///   Choices → Week             the voice path, when find_group returned
///                              several plausible matches
///
/// Voice can also skip straight to the timetable: the agent's show_schedule
/// pushes lessons into SessionStore and this page follows via PropertyChanged.
/// One renderer serves both paths, which is what stops them drifting apart.
///
/// The week is loaded whole — counts and lessons together — so moving between
/// days is instant and the strip can show which days are free without asking
/// the server per day.
/// </summary>
public partial class SchedulePage : UserControl, IBackNavigable
{
    private int _groupId;
    private int _course;
    private DateTime _selectedDay = DateTime.Today;
    private DateTime _weekAnchor = DateTime.Today;
    private List<GroupDto> _allGroups = new();
    private List<LessonDto> _weekLessons = new();

    public SchedulePage()
    {
        InitializeComponent();
        DataContext = SessionStore.Current;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private async void OnLoaded(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.PropertyChanged -= OnSessionChanged;
        SessionStore.Current.PropertyChanged += OnSessionChanged;

        // The agent may have pushed a schedule (or candidates) before this page
        // was even constructed, so honour existing state before starting fresh.
        if (SessionStore.Current.Lessons.Count > 0
            || !string.IsNullOrEmpty(SessionStore.Current.ScheduleEmptyReason))
        {
            ShowLessons();
            return;
        }
        if (SessionStore.Current.GroupChoices.Count > 0)
        {
            ShowChoices();
            return;
        }
        await LoadCoursesAsync();
    }

    private void OnUnloaded(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.PropertyChanged -= OnSessionChanged;

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.ScheduleEmptyReason)
            || e.PropertyName == nameof(SessionStore.ScheduleGroupName))
        {
            Dispatcher.UIThread.Post(ShowLessons);
        }
    }

    // ── Panel switching ──────────────────────────────────────────────────────

    private void ShowOnly(Control panel)
    {
        CoursePanel.IsVisible = ReferenceEquals(panel, CoursePanel);
        GroupPanel.IsVisible = ReferenceEquals(panel, GroupPanel);
        ChoicesPanel.IsVisible = ReferenceEquals(panel, ChoicesPanel);
        LessonPanel.IsVisible = ReferenceEquals(panel, LessonPanel);
    }

    private void ShowChoices()
    {
        Breadcrumb.Text = LocalizationService.Get("ScheduleWhichGroup");
        ShowOnly(ChoicesPanel);
    }

    private void ShowLessons()
    {
        var s = SessionStore.Current;
        Breadcrumb.Text = s.ScheduleGroupName;

        var empty = s.Lessons.Count == 0;
        EmptyState.IsVisible = empty;
        if (empty)
        {
            // Three reasons, three sentences. Telling someone whose group has
            // NO timetable in HEMIS that "the new year is not published yet"
            // sends them back for something that is never coming.
            var reason = s.ScheduleEmptyReason;
            var noneEver = reason == "group_has_no_schedule";
            var yearMissing = reason == "year_not_published";
            EmptyTitle.Text = LocalizationService.Get(
                noneEver ? "ScheduleNoScheduleTitle"
                : yearMissing ? "ScheduleYearNotPublishedTitle"
                : "ScheduleNoLessonsTitle");
            EmptyBody.Text = LocalizationService.Get(
                noneEver ? "ScheduleNoScheduleBody"
                : yearMissing ? "ScheduleYearNotPublishedBody"
                : "ScheduleNoLessonsBody");
        }
        ShowOnly(LessonPanel);
    }

    // ── Loading ──────────────────────────────────────────────────────────────

    private async Task LoadCoursesAsync()
    {
        Breadcrumb.Text = LocalizationService.Get("ScheduleChooseCourse");
        ShowOnly(CoursePanel);
        var resp = await KioskApi.GetCoursesAsync();
        CourseList.ItemsSource = resp?.Items;
    }

    private async Task LoadGroupsAsync(int course)
    {
        _course = course;
        Breadcrumb.Text = string.Format(
            LocalizationService.Get("ScheduleCourseLabel"), course);
        ShowOnly(GroupPanel);
        GroupFilter.Text = "";
        var resp = await KioskApi.GetGroupsAsync(course: course);
        _allGroups = resp?.Items ?? new List<GroupDto>();
        GroupList.ItemsSource = _allGroups;
    }

    /// <summary>Fetch a week and show one day of it.
    ///
    /// `anchor` picks the week; `focus` picks the day inside it. Passing null
    /// for the anchor lets the backend choose the group's last taught week —
    /// over the summer break the current week is empty for every group in the
    /// institute, so opening on it would show a blank screen to everyone.</summary>
    private async Task LoadWeekAsync(int groupId, DateTime? anchor, DateTime? focus = null)
    {
        _groupId = groupId;
        var resp = await KioskApi.GetWeekAsync(groupId, anchor);
        var s = SessionStore.Current;

        if (resp is null)
        {
            // Backend unreachable. Reuse the free-day copy rather than
            // inventing an error state: the next move is the same either way.
            s.SetLessons(Array.Empty<LessonDto>());
            s.ScheduleEmptyReason = "no_lessons_that_day";
            ShowLessons();
            return;
        }

        _weekLessons = resp.Lessons;
        s.ScheduleGroupName = resp.Group?.Name ?? "";

        // Land on the day the visitor asked for; otherwise the first day that
        // actually has classes, so the week never opens on a blank Sunday.
        var busiest = resp.Days.FirstOrDefault(d => d.Count > 0);
        _selectedDay = focus
            ?? ParseDay(busiest?.Date)
            ?? ParseDay(resp.WeekStart)
            ?? DateTime.Today;
        _weekAnchor = _selectedDay;

        s.SetWeek(resp.Days, _selectedDay);
        ApplyDay();
    }

    private static DateTime? ParseDay(string? iso) =>
        DateTime.TryParseExact(
            iso ?? "", "yyyy-MM-dd",
            System.Globalization.CultureInfo.InvariantCulture,
            System.Globalization.DateTimeStyles.None, out var d) ? d : null;

    /// <summary>Show one day out of the week already in memory. No network —
    /// that is the whole point of fetching the week in one call.</summary>
    private void ApplyDay()
    {
        var s = SessionStore.Current;
        var iso = _selectedDay.ToString("yyyy-MM-dd");
        var forDay = _weekLessons.Where(l => l.Date == iso).ToList();

        s.SelectWeekDay(_selectedDay);
        s.SetLessons(forDay);
        s.ScheduleRangeLabel = LocalizationService.FormatDate(
            _selectedDay, LocalizationService.Current);
        s.ScheduleEmptyReason = forDay.Count == 0
            ? (_weekLessons.Count == 0 ? "group_has_no_schedule" : "no_lessons_that_day")
            : "";
        ShowLessons();
    }

    // ── Handlers ─────────────────────────────────────────────────────────────

    private async void OnCourseClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is not CourseDto c) return;
        try { await LoadGroupsAsync(c.Course); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] groups: {ex.Message}"); }
    }

    /// <summary>Client-side filter over the loaded course. A course holds up to
    /// 45 groups and scrolling to "301-B" past every other one is the slowest
    /// part of the touch path.</summary>
    private void OnGroupFilterChanged(object? sender, TextChangedEventArgs e)
    {
        var q = (GroupFilter.Text ?? "").Trim();
        GroupList.ItemsSource = q.Length == 0
            ? _allGroups
            : _allGroups.Where(g =>
                  g.Name.Contains(q, StringComparison.OrdinalIgnoreCase)
                  || g.Specialty.Contains(q, StringComparison.OrdinalIgnoreCase))
              .ToList();
    }

    private async void OnGroupClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is not GroupDto g) return;
        try { await LoadWeekAsync(g.Id, null); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] week: {ex.Message}"); }
    }

    private void OnDayClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is not WeekDayCell cell) return;
        _selectedDay = cell.Date;
        ApplyDay();
    }

    private async void OnPrevWeek(object? sender, RoutedEventArgs e) =>
        await ShiftWeek(-7);

    private async void OnNextWeek(object? sender, RoutedEventArgs e) =>
        await ShiftWeek(7);

    private async Task ShiftWeek(int days)
    {
        if (_groupId == 0) return;
        var target = _weekAnchor.AddDays(days);
        try { await LoadWeekAsync(_groupId, target, target); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] shift: {ex.Message}"); }
    }

    private async void OnToday(object? sender, RoutedEventArgs e)
    {
        if (_groupId == 0) return;
        try { await LoadWeekAsync(_groupId, DateTime.Today, DateTime.Today); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] today: {ex.Message}"); }
    }

    // ── Date picker ──────────────────────────────────────────────────────────

    private void OnPickDate(object? sender, RoutedEventArgs e)
    {
        // Open on the day already showing, so "next week" is one tap rather
        // than paging back across a summer's worth of months.
        DayCalendar.SelectedDate = _selectedDay;
        DayCalendar.DisplayDate = _selectedDay;
        DatePickerOverlay.IsVisible = true;
    }

    private void OnCancelDate(object? sender, RoutedEventArgs e) =>
        DatePickerOverlay.IsVisible = false;

    private async void OnConfirmDate(object? sender, RoutedEventArgs e)
    {
        DatePickerOverlay.IsVisible = false;
        if (DayCalendar.SelectedDate is not { } d || _groupId == 0) return;
        try { await LoadWeekAsync(_groupId, d, d); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] date: {ex.Message}"); }
    }

    // ── Back ─────────────────────────────────────────────────────────────────

    /// <summary>Week → groups → courses. The date overlay counts as a level of
    /// its own so Back dismisses it rather than skipping past the timetable
    /// underneath.</summary>
    public bool TryGoBack()
    {
        if (DatePickerOverlay.IsVisible)
        {
            DatePickerOverlay.IsVisible = false;
            return true;
        }
        if (LessonPanel.IsVisible || ChoicesPanel.IsVisible)
        {
            OnBackToGroups(null, new RoutedEventArgs());
            return true;
        }
        if (GroupPanel.IsVisible)
        {
            _ = LoadCoursesAsync();
            return true;
        }
        return false;
    }

    private async void OnBackToGroups(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        s.SetLessons(Array.Empty<LessonDto>());
        s.WeekDays.Clear();
        s.ScheduleEmptyReason = "";
        s.ScheduleGroupName = "";
        s.ScheduleRangeLabel = "";
        _groupId = 0;
        _weekLessons = new List<LessonDto>();
        try
        {
            if (_course != 0) await LoadGroupsAsync(_course);
            else await LoadCoursesAsync();
        }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] back: {ex.Message}"); }
    }
}
