using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Interactivity;
using Kiosk.App.Identity;

namespace Kiosk.App.Controls;

public partial class RevokedOverlay : UserControl
{
    public RevokedOverlay() { InitializeComponent(); }

    /// <summary>Operator triggers re-enrollment: wipe the stored key + open the
    /// EnrollmentWindow so the new 12-char code can be entered.</summary>
    private void OnReenrollClicked(object? sender, RoutedEventArgs e)
    {
        DeviceKeyStore.Clear();
        if (App.Current?.ApplicationLifetime is not IClassicDesktopStyleApplicationLifetime desktop)
            return;

        // Capture the previous MainWindow before swapping — closing it inside
        // an enumeration over desktop.Windows blows up with a CollectionModified.
        var previous = desktop.MainWindow;
        var enroll = new EnrollmentWindow();
        desktop.MainWindow = enroll;
        enroll.Show();
        previous?.Close();
    }
}
