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
///   Faculty → Group → Lessons     the touch path
///   Choices → Lessons             the voice path, when find_group returned
///                                 several plausible matches
///
/// Voice can also skip straight to Lessons: the agent's show_schedule pushes the
/// list into SessionStore and this page follows via PropertyChanged. Keeping one
/// lesson renderer for both paths is what stops the two surfaces drifting apart.
/// </summary>
public partial class SchedulePage : UserControl
{
    /// <summary>What a freshly picked group opens on.
    ///
    /// NOT "today". The academic year runs roughly September–June, so for a
    /// third of the year — including the whole admissions season, when the
    /// lobby is busiest — "today" is empty for every group in the institute and
    /// the kiosk reads as broken. The group's last taught week always has
    /// something in it, and the range bar above the list says which week it is.
    /// </summary>
    private const string DefaultScope = "last_taught_week";

    private int _groupId;
    private int _facultyId;
    private string _scope = DefaultScope;
    private DateTime? _pickedDate;
    private List<GroupDto> _allGroups = new();

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
        await LoadFacultiesAsync();
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
        FacultyPanel.IsVisible = ReferenceEquals(panel, FacultyPanel);
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
        if (!string.IsNullOrEmpty(s.ScheduleScope)) _scope = s.ScheduleScope;
        UpdateScopeButtons();

        // Say out loud when the timetable on screen is not the current week —
        // the dates alone do not tell a visitor that, and being wrong about
        // which week you are reading sends you to a room on the wrong day.
        RangeNote.Text = _scope == "last_taught_week"
            ? LocalizationService.Get("ScheduleLastTaughtNote")
            : "";

        var empty = s.Lessons.Count == 0;
        EmptyState.IsVisible = empty;
        if (empty)
        {
            var yearMissing = s.ScheduleEmptyReason == "year_not_published";
            EmptyTitle.Text = LocalizationService.Get(
                yearMissing ? "ScheduleYearNotPublishedTitle" : "ScheduleNoLessonsTitle");
            EmptyBody.Text = LocalizationService.Get(
                yearMissing ? "ScheduleYearNotPublishedBody" : "ScheduleNoLessonsBody");
            // Only offer the last taught week when we are not already showing
            // it — otherwise the button reloads the empty screen you are on.
            LastYearButton.IsVisible = yearMissing && _scope != "last_taught_week";
        }
        ShowOnly(LessonPanel);
    }

    private void UpdateScopeButtons()
    {
        SetActive(ScopeLast, _scope == "last_taught_week");
        SetActive(ScopeToday, _scope == "today");
        SetActive(ScopeTomorrow, _scope == "tomorrow");
        SetActive(ScopeDate, _scope is "date" or "week_of");
    }

    private static void SetActive(Button b, bool active)
    {
        if (active) { if (!b.Classes.Contains("active")) b.Classes.Add("active"); }
        else b.Classes.Remove("active");
    }

    // ── Loading ──────────────────────────────────────────────────────────────

    private async Task LoadFacultiesAsync()
    {
        Breadcrumb.Text = LocalizationService.Get("ScheduleChooseFaculty");
        ShowOnly(FacultyPanel);
        var resp = await KioskApi.GetFacultiesAsync();
        FacultyList.ItemsSource = resp?.Items;
    }

    private async Task LoadGroupsAsync(int facultyId, string facultyName)
    {
        _facultyId = facultyId;
        Breadcrumb.Text = facultyName;
        ShowOnly(GroupPanel);
        GroupFilter.Text = "";
        var resp = await KioskApi.GetGroupsAsync(facultyId);
        _allGroups = resp?.Items ?? new List<GroupDto>();
        GroupList.ItemsSource = _allGroups;
    }

    private async Task LoadLessonsAsync(int groupId, string scope, DateTime? onDate = null)
    {
        _groupId = groupId;
        _scope = scope;
        _pickedDate = onDate;
        var resp = await KioskApi.GetLessonsAsync(groupId, scope, onDate);
        var s = SessionStore.Current;
        if (resp is not null)
        {
            s.SetLessons(resp.Lessons);
            s.ScheduleGroupName = resp.Group?.Name ?? "";
            s.ScheduleEmptyReason = resp.EmptyReason;
        }
        else
        {
            // Backend unreachable. Reuse the free-day copy rather than inventing
            // an error state: the visitor's next move is the same either way.
            s.SetLessons(Array.Empty<LessonDto>());
            s.ScheduleEmptyReason = "no_lessons_that_day";
        }
        s.ScheduleScope = scope;
        ShowLessons();
    }

    // ── Handlers ─────────────────────────────────────────────────────────────

    private async void OnFacultyClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is not FacultyDto f) return;
        try { await LoadGroupsAsync(f.Id, f.Name); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] groups: {ex.Message}"); }
    }

    /// <summary>Client-side filter over the loaded faculty. A faculty can hold
    /// several hundred groups and scrolling to "301-B" past every first-year
    /// group is the slowest part of the touch path.</summary>
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
        try { await LoadLessonsAsync(g.Id, DefaultScope); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] lessons: {ex.Message}"); }
    }

    private async void OnScopeLast(object? sender, RoutedEventArgs e) => await Reload("last_taught_week");
    private async void OnScopeToday(object? sender, RoutedEventArgs e) => await Reload("today");
    private async void OnScopeTomorrow(object? sender, RoutedEventArgs e) => await Reload("tomorrow");

    private async Task Reload(string scope, DateTime? onDate = null)
    {
        if (_groupId == 0) return;
        try { await LoadLessonsAsync(_groupId, scope, onDate); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] reload: {ex.Message}"); }
    }

    // ── Date picker ──────────────────────────────────────────────────────────

    private void OnPickDate(object? sender, RoutedEventArgs e)
    {
        // Open on the day already being shown, so "next day" is one tap rather
        // than navigating back from today across a summer's worth of months.
        var anchor = _pickedDate
            ?? SessionStore.Current.LessonDays.FirstOrDefault(d => d.Date != default)?.Date
            ?? DateTime.Today;
        DayCalendar.SelectedDate = anchor;
        DayCalendar.DisplayDate = anchor;
        DatePickerOverlay.IsVisible = true;
    }

    private void OnCancelDate(object? sender, RoutedEventArgs e) =>
        DatePickerOverlay.IsVisible = false;

    /// <summary>Selecting a day does not load it — the visitor still chooses
    /// between that day and its whole week. Loading on selection would make the
    /// week button unreachable.</summary>
    private void OnCalendarDateChanged(object? sender, SelectionChangedEventArgs e) { }

    private async void OnConfirmDate(object? sender, RoutedEventArgs e)
    {
        DatePickerOverlay.IsVisible = false;
        if (DayCalendar.SelectedDate is { } d) await Reload("date", d);
    }

    private async void OnConfirmDateWeek(object? sender, RoutedEventArgs e)
    {
        DatePickerOverlay.IsVisible = false;
        if (DayCalendar.SelectedDate is { } d) await Reload("week_of", d);
    }

    private async void OnBackToGroups(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        s.SetLessons(Array.Empty<LessonDto>());
        s.ScheduleEmptyReason = "";
        s.ScheduleGroupName = "";
        _groupId = 0;
        _pickedDate = null;
        _scope = DefaultScope;
        try
        {
            if (_facultyId != 0) await LoadGroupsAsync(_facultyId, Breadcrumb.Text ?? "");
            else await LoadFacultiesAsync();
        }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] back: {ex.Message}"); }
    }
}
