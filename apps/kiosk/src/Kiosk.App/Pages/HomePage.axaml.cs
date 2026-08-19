using System.Linq;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Kiosk.App.Layout;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>Home menu. Each tile resets any half-finished flow before
/// navigating: a visitor who walked away mid-appeal leaves the step machine
/// dirty, and the next person must not land in someone else's form.</summary>
public partial class HomePage : UserControl
{
    public HomePage()
    {
        InitializeComponent();
        ApplyTileLayout(LayoutService.Current);
        // The page is cached for the life of the process (SessionStore holds
        // one instance), so there is nothing to unsubscribe from — and staying
        // subscribed means a shape change while the visitor is on another
        // screen still lands before they come back here.
        LayoutService.ShapeChanged += ApplyTileLayout;
    }

    /// <summary>Lay the six service tiles out for the panel this kiosk is on:
    /// two columns of three standing up, three columns of two lying down.
    ///
    /// Done here rather than in the metrics dictionary because a Grid's row and
    /// column definitions are a collection, not a value a ResourceDictionary
    /// can hold. Tiles are read in document order, so the reading order stays
    /// the same on both shapes — AI, library, applicants, then appeals,
    /// timetable, reception — and adding a seventh service needs no change
    /// here beyond dropping it in the XAML.</summary>
    private void ApplyTileLayout(ScreenShape shape)
    {
        var count = TileGrid.Children.Count;
        if (count == 0) return;

        var landscape = shape == ScreenShape.Landscape;
        var cols = landscape ? 3 : 2;
        var rows = (count + cols - 1) / cols;

        TileGrid.ColumnDefinitions =
            new ColumnDefinitions(string.Join(",", Enumerable.Repeat("*", cols)));
        // Landscape has no spare height to leave under the tiles, so the rows
        // share what is left below the hero. Portrait has plenty, and tiles
        // that stretched into it would look like a stretched grid rather than
        // a menu — so there they keep their natural height at the top.
        TileGrid.RowDefinitions =
            new RowDefinitions(string.Join(",", Enumerable.Repeat(landscape ? "*" : "Auto", rows)));
        TileGrid.VerticalAlignment = landscape
            ? Avalonia.Layout.VerticalAlignment.Stretch
            : Avalonia.Layout.VerticalAlignment.Top;

        for (var i = 0; i < count; i++)
        {
            var tile = TileGrid.Children[i];
            Grid.SetRow(tile, i / cols);
            Grid.SetColumn(tile, i % cols);
        }
    }

    private static void Go(KioskPage page)
    {
        var s = SessionStore.Current;
        s.SubmitStep = SubmitStep.Idle;
        s.Navigate(page);
    }

    private void OnTileAi(object? sender, RoutedEventArgs e) => Go(KioskPage.Ai);
    private void OnTileLibrary(object? sender, RoutedEventArgs e) => Go(KioskPage.Library);
    private void OnTileAbituriyent(object? sender, RoutedEventArgs e) => Go(KioskPage.Abituriyent);
    private void OnTileMurojat(object? sender, RoutedEventArgs e) => Go(KioskPage.Murojat);
    private void OnTileSchedule(object? sender, RoutedEventArgs e) => Go(KioskPage.Jadval);
    private void OnTileReception(object? sender, RoutedEventArgs e) => Go(KioskPage.Qabul);
}
