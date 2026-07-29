using System.Linq;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.VisualTree;
using Kiosk.App.State;

namespace Kiosk.App.Controls;

public partial class NavBar : UserControl
{
    public NavBar()
    {
        InitializeComponent();
    }

    /// <summary>Back steps within the page when the page has depth, and leaves
    /// for Home only when it does not.
    ///
    /// Both buttons used to call Navigate(Home), which made Back a second Home
    /// button: on the timetable it threw away the faculty and group the visitor
    /// had just drilled through, so reaching the neighbouring group meant
    /// starting from the faculty list again.
    ///
    /// The owning page is found by walking up the visual tree rather than being
    /// injected — NavBar is dropped into each page's XAML with no code-behind
    /// wiring, and that is worth keeping.</summary>
    private void OnBack(object? sender, RoutedEventArgs e)
    {
        var page = this.GetVisualAncestors().OfType<IBackNavigable>().FirstOrDefault();
        if (page?.TryGoBack() == true) return;
        SessionStore.Current.Navigate(KioskPage.Home);
    }

    private void OnHome(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.Navigate(KioskPage.Home);
}
