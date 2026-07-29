using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>Degree programmes for applicants. The list loads over HTTP so the
/// page works with no voice session at all; the agent's show_directions /
/// show_direction write into the same SessionStore collections, so voice and
/// touch stay on one screen state.
///
/// Tapping a row re-fetches the programme from the detail endpoint rather than
/// reusing the list row: the subject list is the reason anyone opens this
/// screen and the list endpoint does not carry it (94 programmes × 10 subjects
/// would be most of a megabyte for a list nobody reads in full).</summary>
public partial class AbituriyentPage : UserControl, IBackNavigable
{
    private List<DirectionDto> _all = new();

    public AbituriyentPage()
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
        RenderDetail();

        if (SessionStore.Current.Directions.Count > 0)
        {
            // The agent already pushed the list; don't refetch over it.
            _all = SessionStore.Current.Directions.ToList();
            DirectionList.ItemsSource = _all;
            return;
        }
        try
        {
            var resp = await KioskApi.GetDirectionsAsync();
            if (resp is null) return;
            var s = SessionStore.Current;
            s.Directions.Clear();
            foreach (var d in resp.Items) s.Directions.Add(d);
            _all = resp.Items;
            DirectionList.ItemsSource = _all;
            Breadcrumb.Text = string.Format(
                LocalizationService.Get("AbituriyentCount"), _all.Count);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[abituriyent] load: {ex.Message}");
        }
    }

    private void OnUnloaded(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.PropertyChanged -= OnSessionChanged;

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.SelectedDirection))
            Dispatcher.UIThread.Post(RenderDetail);
    }

    private void OnFilterChanged(object? sender, TextChangedEventArgs e)
    {
        var q = (DirectionFilter.Text ?? "").Trim();
        DirectionList.ItemsSource = q.Length == 0
            ? _all
            : _all.Where(d =>
                  d.Name.Contains(q, StringComparison.OrdinalIgnoreCase)
                  || d.Faculty.Contains(q, StringComparison.OrdinalIgnoreCase)
                  || d.EducationType.Contains(q, StringComparison.OrdinalIgnoreCase))
              .ToList();
    }

    private void RenderDetail()
    {
        var d = SessionStore.Current.SelectedDirection;
        DetailPanel.IsVisible = d is not null;
        ListPanel.IsVisible = d is null;
        if (d is null)
        {
            Breadcrumb.Text = _all.Count == 0
                ? ""
                : string.Format(LocalizationService.Get("AbituriyentCount"), _all.Count);
            return;
        }

        Breadcrumb.Text = d.EducationType;
        DetailMark.Programme = d;
        DetailName.Text = d.Name;
        DetailType.Text = d.EducationType;
        DetailCode.Text = d.Code;
        DetailFaculty.Text = d.Faculty;
        DetailGroupCount.Text = d.GroupCount.ToString();
        DetailLanguages.ItemsSource = d.Languages;
        DetailSubjects.ItemsSource = d.Subjects;

        // A programme with no groups yet has nothing to aggregate, and one
        // reached through the list endpoint has no subjects. Hiding the empty
        // card beats showing a heading over blank space.
        FactsCard.IsVisible = d.Languages.Count > 0 || d.GroupCount > 0;
        SubjectsCard.IsVisible = d.Subjects.Count > 0;
    }

    private async void OnDirectionClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is not DirectionDto d) return;
        // Show the row we already have straight away, then swap in the fuller
        // record — the screen must not sit blank while the fetch runs.
        SessionStore.Current.SelectedDirection = d;
        Tell($"the programme \"{d.Name}\" ({d.EducationType}, {d.Faculty})");
        try
        {
            var resp = await KioskApi.GetDirectionAsync(d.Id);
            if (resp?.Item is { } full) SessionStore.Current.SelectedDirection = full;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[abituriyent] detail: {ex.Message}");
        }
    }

    /// <summary>Detail → list.</summary>
    public bool TryGoBack()
    {
        if (SessionStore.Current.SelectedDirection is null) return false;
        SessionStore.Current.SelectedDirection = null;
        return true;
    }

    private void OnBackToList(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.SelectedDirection = null;
        Tell("the full programme list");
    }

    /// <summary>Tell the agent what the visitor opened by touch, so it does not
    /// ask about a programme already on screen.</summary>
    private static void Tell(string where)
    {
        var rt = KioskRuntime.Current;
        if (rt is null || !rt.IsActive) return;
        _ = rt.SendUiStateAsync($"Abituriyent — {where}");
    }
}
