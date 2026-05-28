using System;
using Avalonia.Controls;
using Avalonia.Interactivity;

namespace Kiosk.App.Controls;

/// <summary>On-screen numeric keypad for the fullscreen kiosk where the
/// Windows touch keyboard is unreliable. Wire it up by setting
/// <see cref="TargetTextBox"/> — every key click appends/erases on that box.
/// Emits <see cref="Cleared"/> when the operator hits the close key (✕)
/// so the host page can collapse the keypad row.</summary>
public partial class NumericKeypad : UserControl
{
    public TextBox? TargetTextBox { get; set; }

    /// <summary>Fires when the close (✕) key is pressed. The host typically
    /// uses this to hide the keypad. The text box value is left intact.</summary>
    public event EventHandler? Cleared;

    public NumericKeypad()
    {
        InitializeComponent();
        AddHandler(Button.ClickEvent, OnAnyButtonClick);
    }

    private void OnAnyButtonClick(object? sender, RoutedEventArgs e)
    {
        if (e.Source is not Button b) return;
        var tag = b.Tag as string ?? "";
        var box = TargetTextBox;
        if (box is null) return;

        switch (tag)
        {
            case "back":
                // Remove the LAST DIGIT, not the last character. The phone
                // box (QabulPage) renders a formatted mask like "+998 12 -
                // 345 - __ - __" where unentered slots are "_" placeholders
                // — naïve `t[..^1]` would just eat the "_" and the user
                // would have to press back twice per actual digit. AdminPin's
                // box is digit-only so this still acts like "remove last
                // char" there.
                var t = box.Text ?? "";
                int lastDigit = -1;
                for (int i = t.Length - 1; i >= 0; i--)
                {
                    if (char.IsDigit(t[i])) { lastDigit = i; break; }
                }
                if (lastDigit >= 0) box.Text = t[..lastDigit] + t[(lastDigit + 1)..];
                break;
            case "clear":
                Cleared?.Invoke(this, EventArgs.Empty);
                break;
            default:
                if (tag.Length == 1 && char.IsDigit(tag[0]))
                {
                    box.Text = (box.Text ?? "") + tag;
                    box.CaretIndex = (box.Text ?? "").Length;
                }
                break;
        }
    }
}
