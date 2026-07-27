using System;
using System.ComponentModel;
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
    private int _groupId;
    private int _facultyId;
    private string _scope = "today";

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

        var empty = s.Lessons.Count == 0;
        EmptyState.IsVisible = empty;
        if (empty)
        {
            var yearMissing = s.ScheduleEmptyReason == "year_not_published";
            EmptyTitle.Text = LocalizationService.Get(
                yearMissing ? "ScheduleYearNotPublishedTitle" : "ScheduleNoLessonsTitle");
            EmptyBody.Text = LocalizationService.Get(
                yearMissing ? "ScheduleYearNotPublishedBody" : "ScheduleNoLessonsBody");
            // Only offer last year's week when the whole year is missing —
            // after a free Sunday it would just be confusing.
            LastYearButton.IsVisible = yearMissing;
        }
        ShowOnly(LessonPanel);
    }

    private void UpdateScopeButtons()
    {
        SetActive(ScopeToday, _scope == "today");
        SetActive(ScopeTomorrow, _scope == "tomorrow");
        SetActive(ScopeWeek, _scope is "week" or "last_taught_week");
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
        var resp = await KioskApi.GetGroupsAsync(facultyId);
        GroupList.ItemsSource = resp?.Items;
    }

    private async Task LoadLessonsAsync(int groupId, string scope)
    {
        _groupId = groupId;
        _scope = scope;
        var resp = await KioskApi.GetLessonsAsync(groupId, scope);
        var s = SessionStore.Current;
        s.Lessons.Clear();
        if (resp is not null)
        {
            foreach (var l in resp.Lessons) s.Lessons.Add(l);
            s.ScheduleGroupName = resp.Group?.Name ?? "";
            s.ScheduleEmptyReason = resp.EmptyReason;
        }
        else
        {
            // Backend unreachable. Reuse the free-day copy rather than inventing
            // an error state: the visitor's next move is the same either way.
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

    private async void OnGroupClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is not GroupDto g) return;
        try { await LoadLessonsAsync(g.Id, "today"); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] lessons: {ex.Message}"); }
    }

    private async void OnScopeToday(object? sender, RoutedEventArgs e) => await Reload("today");
    private async void OnScopeTomorrow(object? sender, RoutedEventArgs e) => await Reload("tomorrow");
    private async void OnScopeWeek(object? sender, RoutedEventArgs e) => await Reload("week");
    private async void OnShowLastYear(object? sender, RoutedEventArgs e) => await Reload("last_taught_week");

    private async Task Reload(string scope)
    {
        if (_groupId == 0) return;
        try { await LoadLessonsAsync(_groupId, scope); }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] reload: {ex.Message}"); }
    }

    private async void OnBackToGroups(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        s.Lessons.Clear();
        s.ScheduleEmptyReason = "";
        s.ScheduleGroupName = "";
        _groupId = 0;
        try
        {
            if (_facultyId != 0) await LoadGroupsAsync(_facultyId, Breadcrumb.Text ?? "");
            else await LoadFacultiesAsync();
        }
        catch (Exception ex) { Console.Error.WriteLine($"[schedule] back: {ex.Message}"); }
    }
}
