using Avalonia.Controls;
using Avalonia.Interactivity;
using Kiosk.App.State;

namespace Kiosk.App.Controls;

public partial class NavBar : UserControl
{
    public NavBar()
    {
        InitializeComponent();
    }

    private void OnBack(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.Navigate(KioskPage.Home);

    private void OnHome(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.Navigate(KioskPage.Home);
}
