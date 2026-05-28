using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Interactivity;

namespace Kiosk.App.Identity;

public partial class EnrollmentWindow : Window
{
    public EnrollmentWindow()
    {
        InitializeComponent();
        EnrollButton.Click += OnEnrollClicked;
    }

    private async void OnEnrollClicked(object? sender, RoutedEventArgs e)
    {
        var backendUrl = (BackendUrlBox.Text ?? "").Trim();
        var code = (CodeBox.Text ?? "").Trim();
        if (string.IsNullOrEmpty(backendUrl) || string.IsNullOrEmpty(code))
        {
            StatusText.Text = "Bayranıs URL hám kod kerek.";
            return;
        }

        StatusText.Text = "Enrollment etilip atır...";
        EnrollButton.IsEnabled = false;

        var result = await EnrollmentService.EnrollAsync(backendUrl, code);
        if (!result.Success)
        {
            StatusText.Text = $"Qátelik: {result.Error}";
            EnrollButton.IsEnabled = true;
            return;
        }

        StatusText.Text = "Tabıslı! Bas oynaǵa ótip atır...";
        if (App.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var main = new MainWindow();
            desktop.MainWindow = main;
            main.Show();
            Close();
        }
    }
}
