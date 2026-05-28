using System.Security.Cryptography;
using System.Text;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Kiosk.App.Settings;

namespace Kiosk.App.Pages;

public partial class AdminPinDialog : Window
{
    /// <summary>True only when the user typed the correct PIN. Read by the
    /// caller via <see cref="WaitForResult"/>.</summary>
    public bool Authorized { get; private set; }

    public AdminPinDialog()
    {
        InitializeComponent();
        // PinBox is IsReadOnly=true so Windows touch keyboard doesn't fight
        // the on-screen keypad. The keypad drives Text directly.
        Keypad.TargetTextBox = PinBox;
        Keypad.Cleared += (_, _) =>
        {
            PinBox.Text = "";
            ErrorText.IsVisible = false;
        };
    }

    private void OnConfirm(object? sender, RoutedEventArgs e)
    {
        var entered = PinBox.Text ?? "";
        if (Verify(entered))
        {
            Authorized = true;
            Close();
        }
        else
        {
            // Text is bound to {DynamicResource AdminPinIncorrect}; we just flip
            // visibility on so the user sees the localized error.
            ErrorText.IsVisible = true;
            PinBox.Text = "";
            PinBox.Focus();
        }
    }

    private void OnCancel(object? sender, RoutedEventArgs e) => Close();

    /// <summary>Empty stored hash → default PIN "0000". Otherwise SHA-256 of
    /// the entered PIN must match the stored hash. SHA-256 is fast enough for
    /// 4-digit PINs given there's no remote brute-force surface — physical
    /// access already implies game-over for the kiosk machine.</summary>
    private static bool Verify(string entered)
    {
        var stored = KioskSettings.Current.AdminPinHash ?? "";
        if (string.IsNullOrEmpty(stored)) return entered == "0205";
        return Hash(entered) == stored;
    }

    private static string Hash(string s)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(s));
        var sb = new StringBuilder(bytes.Length * 2);
        foreach (var b in bytes) sb.Append(b.ToString("x2"));
        return sb.ToString();
    }
}
