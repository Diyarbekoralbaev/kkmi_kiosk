using System;
using System.ComponentModel;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>Degree programmes for applicants. The list loads over HTTP so the
/// page works with no voice session at all; the agent's show_directions /
/// show_direction write into the same SessionStore collections, so voice and
/// touch stay on one screen state.</summary>
public partial class AbituriyentPage : UserControl
{
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

        // The agent may already have pushed the list; don't refetch over it.
        if (SessionStore.Current.Directions.Count > 0) return;
        try
        {
            var resp = await KioskApi.GetDirectionsAsync();
            if (resp is null) return;
            var s = SessionStore.Current;
            s.Directions.Clear();
            foreach (var d in resp.Items) s.Directions.Add(d);
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

    private void RenderDetail()
    {
        var d = SessionStore.Current.SelectedDirection;
        DetailCard.IsVisible = d is not null;
        if (d is null) return;
        DetailName.Text = d.Name;
        DetailType.Text = d.EducationType;
        DetailCode.Text = d.Code;
        DetailFaculty.Text = d.Faculty;
    }

    private void OnDirectionClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is DirectionDto d)
            SessionStore.Current.SelectedDirection = d;
    }
}
